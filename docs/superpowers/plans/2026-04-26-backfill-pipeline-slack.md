# Backfill Pipeline + Slack Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spec `2026-04-26-backfill-pipeline-slack-design.md`의 공통 backfill 파이프라인 (`discover → filter → redact → embed → store`) 과 Slack 레퍼런스 어댑터 + `breadmind kb backfill` CLI를 마이그레이션 010 위에 구현한다.

**Architecture:** `BackfillJob` ABC + adapter 분리 (`SlackBackfillAdapter`) + `BackfillRunner` 5단계 파이프라인 (redact/embed/store는 runner 소유). 마이그레이션 010이 `org_knowledge`에 source provenance 5컬럼을 추가하고 `kb_backfill_jobs` / `kb_backfill_org_budget` 두 테이블을 신설한다. `HourlyPageBudget`은 `(org_id, instance_id)` 키로 확장한다.

**Tech Stack:** Python 3.12+, asyncpg, pgvector, pytest-asyncio (`asyncio_mode = "auto"`), fastembed/Ollama/API embedding (기존 `EmbeddingService`), aiohttp (Slack Web API), argparse (`breadmind` CLI).

---

## File Structure

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `src/breadmind/kb/backfill/__init__.py` | 패키지 export (`BackfillJob`, `BackfillItem`, `JobReport`, `JobProgress`, `BackfillRunner`) | **신규** |
| `src/breadmind/kb/backfill/base.py` | `BackfillJob` ABC + `BackfillItem` / `JobProgress` / `JobReport` dataclass + `Skipped` 예외 | **신규** |
| `src/breadmind/kb/backfill/runner.py` | 파이프라인 오케스트레이터: ACL prepare → discover → filter → redact → embed → store + 체크포인트 | **신규** |
| `src/breadmind/kb/backfill/budget.py` | `OrgMonthlyBudget` (per-org 월 token ceiling) + `OrgMonthlyBudgetExceeded` | **신규** |
| `src/breadmind/kb/backfill/checkpoint.py` | `kb_backfill_jobs` upsert / 재개 cursor 로드 | **신규** |
| `src/breadmind/kb/backfill/slack.py` | `SlackBackfillAdapter` (history+replies+members, 휴리스틱) | **신규** |
| `src/breadmind/kb/backfill/cli.py` | `breadmind kb backfill <slack|resume|list|cancel>` argparse subcommands + dry-run 출력 | **신규** |
| `src/breadmind/kb/connectors/rate_limit.py` | `HourlyPageBudget`에 `(org_id, instance_id)` 키 차원 추가 | 수정 |
| `src/breadmind/storage/migrations/versions/010_kb_backfill.py` | spec §5 DDL 그대로 (org_knowledge 5컬럼 + 2 신규 테이블 + 4 인덱스) | **신규** |
| `src/breadmind/main.py` | `kb` subparser + `backfill` 위임 라우팅 | 수정 |
| `tests/kb/backfill/__init__.py` | 패키지 마커 | **신규** |
| `tests/kb/backfill/conftest.py` | `FakeSlackSession`, `FakeRedactor`, `FakeEmbedder`, `mem_backfill_db` fixture | **신규** |
| `tests/kb/backfill/test_base.py` | `BackfillItem`/`JobProgress`/`JobReport`/ABC 단위 | **신규** |
| `tests/kb/backfill/test_runner.py` | 파이프라인 순서·dry-run·token_budget·error 임계 | **신규** |
| `tests/kb/backfill/test_budget.py` | `OrgMonthlyBudget` upsert + 초과 동작 | **신규** |
| `tests/kb/backfill/test_rate_limit_instance.py` | `(org_id, instance_id)` 분리 + legacy `(org_id,)` 백워드 호환 | **신규** |
| `tests/kb/backfill/test_slack_filter.py` | 4 휴리스틱 + ACL 라벨 | **신규** |
| `tests/kb/backfill/test_slack_discover.py` | history/replies pagination, 429 Retry-After, 스레드 롤업 | **신규** |
| `tests/kb/backfill/test_checkpoint.py` | 50개/30s 체크포인트 + resume cursor 라운드트립 | **신규** |
| `tests/kb/backfill/test_cli.py` | argparse 파싱 + dry-run 골든 출력 + confirm 흐름 | **신규** |
| `tests/storage/test_migration_010.py` | upgrade/downgrade + 부분 unique index 동작 | **신규** |
| `tests/integration/kb/backfill/test_e2e_slack.py` | testcontainers Postgres + 가짜 Slack 클라이언트 e2e | **신규** |

---

## Task 1: Migration 010 — org_knowledge 컬럼 + kb_backfill_jobs + kb_backfill_org_budget

**Files:** Create `src/breadmind/storage/migrations/versions/010_kb_backfill.py`. Create `tests/storage/test_migration_010.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/storage/test_migration_010.py`:

  ```python
  from __future__ import annotations
  import uuid
  import pytest
  from breadmind.storage.migrations.versions import (
      _010_kb_backfill as mig,  # accessed via importlib in repo
  )

  pytestmark = pytest.mark.asyncio


  async def test_010_upgrade_adds_org_knowledge_columns(testcontainers_pg):
      conn = testcontainers_pg
      await conn.execute(mig.UPGRADE_SQL)
      cols = {r["column_name"] for r in await conn.fetch(
          "SELECT column_name FROM information_schema.columns "
          "WHERE table_name='org_knowledge'"
      )}
      assert {"source_kind", "source_native_id", "source_created_at",
              "source_updated_at", "parent_ref"} <= cols


  async def test_010_creates_unique_partial_index(testcontainers_pg):
      conn = testcontainers_pg
      await conn.execute(mig.UPGRADE_SQL)
      pid = uuid.uuid4()
      await conn.execute(
          "INSERT INTO org_knowledge (project_id, body, source_kind, source_native_id) "
          "VALUES ($1, 'a', 'slack_msg', 'C1:1.0')", pid)
      with pytest.raises(Exception):  # IntegrityError on duplicate
          await conn.execute(
              "INSERT INTO org_knowledge (project_id, body, source_kind, source_native_id) "
              "VALUES ($1, 'b', 'slack_msg', 'C1:1.0')", pid)


  async def test_010_creates_kb_backfill_jobs(testcontainers_pg):
      conn = testcontainers_pg
      await conn.execute(mig.UPGRADE_SQL)
      cols = {r["column_name"] for r in await conn.fetch(
          "SELECT column_name FROM information_schema.columns "
          "WHERE table_name='kb_backfill_jobs'"
      )}
      assert {"id", "org_id", "source_kind", "source_filter", "instance_id",
              "since_ts", "until_ts", "dry_run", "token_budget", "status",
              "last_cursor", "progress_json", "skipped_json", "started_at",
              "finished_at", "error", "created_by", "created_at"} <= cols


  async def test_010_creates_kb_backfill_org_budget(testcontainers_pg):
      conn = testcontainers_pg
      await conn.execute(mig.UPGRADE_SQL)
      cols = {r["column_name"] for r in await conn.fetch(
          "SELECT column_name FROM information_schema.columns "
          "WHERE table_name='kb_backfill_org_budget'"
      )}
      assert {"org_id", "period_month", "tokens_used", "tokens_ceiling",
              "updated_at"} <= cols


  async def test_010_downgrade_drops_everything(testcontainers_pg):
      conn = testcontainers_pg
      await conn.execute(mig.UPGRADE_SQL)
      await conn.execute(mig.DOWNGRADE_SQL)
      tables = {r["table_name"] for r in await conn.fetch(
          "SELECT table_name FROM information_schema.tables "
          "WHERE table_schema='public'"
      )}
      assert "kb_backfill_jobs" not in tables
      assert "kb_backfill_org_budget" not in tables
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/storage/test_migration_010.py -v`. 예상: `ModuleNotFoundError: ... _010_kb_backfill` (모듈 부재).

- [ ] **Step 3: 최소 구현** — `src/breadmind/storage/migrations/versions/010_kb_backfill.py`:

  ```python
  """Backfill pipeline schema — org_knowledge provenance + jobs + per-org budget.

  Revision ID: 010_kb_backfill
  Revises: 009_episodic_org_id
  Create Date: 2026-04-26
  """
  from alembic import op

  revision = "010_kb_backfill"
  down_revision = "009_episodic_org_id"
  branch_labels = None
  depends_on = None

  UPGRADE_SQL = """
  ALTER TABLE org_knowledge
      ADD COLUMN IF NOT EXISTS source_kind         TEXT,
      ADD COLUMN IF NOT EXISTS source_native_id    TEXT,
      ADD COLUMN IF NOT EXISTS source_created_at   TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS source_updated_at   TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS parent_ref          TEXT;

  CREATE UNIQUE INDEX IF NOT EXISTS uq_org_knowledge_source_native
      ON org_knowledge (project_id, source_kind, source_native_id)
      WHERE source_native_id IS NOT NULL AND superseded_by IS NULL;

  CREATE INDEX IF NOT EXISTS ix_org_knowledge_source_created_at
      ON org_knowledge (project_id, source_created_at DESC)
      WHERE source_created_at IS NOT NULL;

  CREATE INDEX IF NOT EXISTS ix_org_knowledge_source_updated_at
      ON org_knowledge (project_id, source_updated_at DESC)
      WHERE source_updated_at IS NOT NULL;

  CREATE INDEX IF NOT EXISTS ix_org_knowledge_parent_ref
      ON org_knowledge (project_id, parent_ref)
      WHERE parent_ref IS NOT NULL;

  CREATE TABLE IF NOT EXISTS kb_backfill_jobs (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
      source_kind     TEXT NOT NULL,
      source_filter   JSONB NOT NULL,
      instance_id     TEXT NOT NULL,
      since_ts        TIMESTAMPTZ NOT NULL,
      until_ts        TIMESTAMPTZ NOT NULL,
      dry_run         BOOLEAN NOT NULL,
      token_budget    BIGINT NOT NULL,
      status          TEXT NOT NULL,
      last_cursor     TEXT,
      progress_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
      skipped_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
      started_at      TIMESTAMPTZ,
      finished_at     TIMESTAMPTZ,
      error           TEXT,
      created_by      TEXT NOT NULL,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  CREATE INDEX IF NOT EXISTS ix_kb_backfill_org_status
      ON kb_backfill_jobs (org_id, status, created_at DESC);

  CREATE TABLE IF NOT EXISTS kb_backfill_org_budget (
      org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
      period_month    DATE NOT NULL,
      tokens_used     BIGINT NOT NULL DEFAULT 0,
      tokens_ceiling  BIGINT NOT NULL,
      updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, period_month)
  );
  """

  DOWNGRADE_SQL = """
  DROP TABLE IF EXISTS kb_backfill_org_budget;
  DROP INDEX IF EXISTS ix_kb_backfill_org_status;
  DROP TABLE IF EXISTS kb_backfill_jobs;
  DROP INDEX IF EXISTS ix_org_knowledge_parent_ref;
  DROP INDEX IF EXISTS ix_org_knowledge_source_updated_at;
  DROP INDEX IF EXISTS ix_org_knowledge_source_created_at;
  DROP INDEX IF EXISTS uq_org_knowledge_source_native;
  ALTER TABLE org_knowledge
      DROP COLUMN IF EXISTS parent_ref,
      DROP COLUMN IF EXISTS source_updated_at,
      DROP COLUMN IF EXISTS source_created_at,
      DROP COLUMN IF EXISTS source_native_id,
      DROP COLUMN IF EXISTS source_kind;
  """


  def upgrade() -> None:
      op.execute(UPGRADE_SQL)


  def downgrade() -> None:
      op.execute(DOWNGRADE_SQL)
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/storage/test_migration_010.py -v`. 예상: 5 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/storage/migrations/versions/010_kb_backfill.py tests/storage/test_migration_010.py && git commit -m "feat(storage): migration 010 backfill schema (org_knowledge provenance + jobs + budget)"`

---

## Task 2: BackfillItem dataclass + 검증

**Files:** Create `src/breadmind/kb/backfill/__init__.py`, `src/breadmind/kb/backfill/base.py`. Create `tests/kb/backfill/__init__.py`, `tests/kb/backfill/test_base.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_base.py`:

  ```python
  from __future__ import annotations
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.base import BackfillItem


  def _ts() -> datetime:
      return datetime(2026, 1, 1, tzinfo=timezone.utc)


  def test_backfill_item_required_fields():
      item = BackfillItem(
          source_kind="slack_msg",
          source_native_id="C1:1.0",
          source_uri="https://slack/p1",
          source_created_at=_ts(),
          source_updated_at=_ts(),
          title="t",
          body="b",
          author="U1",
      )
      assert item.parent_ref is None
      assert item.extra == {}


  def test_backfill_item_is_frozen():
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="x", source_uri="u",
          source_created_at=_ts(), source_updated_at=_ts(),
          title="t", body="b", author=None)
      with pytest.raises(Exception):  # FrozenInstanceError
          item.body = "z"  # type: ignore[misc]


  def test_backfill_item_parent_ref_format():
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="C1:1.1",
          source_uri="u", source_created_at=_ts(), source_updated_at=_ts(),
          title="t", body="b", author=None,
          parent_ref="slack_msg:C1:1.0")
      assert item.parent_ref.startswith("slack_msg:")


  def test_backfill_item_dual_timestamps_independent():
      created = datetime(2026, 1, 1, tzinfo=timezone.utc)
      updated = datetime(2026, 4, 1, tzinfo=timezone.utc)
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="x", source_uri="u",
          source_created_at=created, source_updated_at=updated,
          title="t", body="b", author=None)
      assert item.source_created_at != item.source_updated_at
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_base.py::test_backfill_item_required_fields -v`. 예상: `ModuleNotFoundError: breadmind.kb.backfill`.

- [ ] **Step 3: 최소 구현** — `src/breadmind/kb/backfill/__init__.py` (빈 파일로 시작) 와 `src/breadmind/kb/backfill/base.py`:

  ```python
  """Common backfill pipeline contract.

  Spec: docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md
  """
  from __future__ import annotations

  from dataclasses import dataclass, field
  from datetime import datetime
  from typing import Any


  @dataclass(frozen=True)
  class BackfillItem:
      source_kind: str
      source_native_id: str
      source_uri: str
      source_created_at: datetime
      source_updated_at: datetime
      title: str
      body: str
      author: str | None
      parent_ref: str | None = None
      extra: dict[str, Any] = field(default_factory=dict)
  ```

  `src/breadmind/kb/backfill/__init__.py`:

  ```python
  from breadmind.kb.backfill.base import BackfillItem

  __all__ = ["BackfillItem"]
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_base.py -v -k backfill_item`. 예상: 4 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/__init__.py src/breadmind/kb/backfill/base.py tests/kb/backfill/__init__.py tests/kb/backfill/test_base.py && git commit -m "feat(kb/backfill): add BackfillItem dataclass with dual timestamps and parent_ref"`

---

## Task 3: JobProgress + JobReport dataclass

**Files:** Modify `src/breadmind/kb/backfill/base.py`. Modify `tests/kb/backfill/test_base.py`.

- [ ] **Step 1: 실패 테스트 추가** — `tests/kb/backfill/test_base.py`에 append:

  ```python
  import uuid
  from breadmind.kb.backfill.base import JobProgress, JobReport


  def test_job_progress_defaults_zero():
      p = JobProgress()
      assert p.discovered == 0 and p.embedded == 0 and p.tokens_consumed == 0
      assert p.last_cursor is None


  def test_job_progress_mutable():
      p = JobProgress()
      p.discovered += 1
      p.last_cursor = "abc"
      assert p.discovered == 1 and p.last_cursor == "abc"


  def test_job_report_skipped_is_dict():
      r = JobReport(
          job_id=uuid.uuid4(), org_id=uuid.uuid4(), source_kind="slack_msg",
          dry_run=True, estimated_count=0, estimated_tokens=0,
          indexed_count=0)
      assert r.skipped == {}
      assert r.sample_titles == [] and r.budget_hit is False
      assert r.cursor is None


  def test_job_report_cursor_is_opaque_str():
      r = JobReport(
          job_id=uuid.uuid4(), org_id=uuid.uuid4(), source_kind="slack_msg",
          dry_run=False, estimated_count=10, estimated_tokens=100,
          indexed_count=10, cursor="1730000000:C1:1.0")
      # Pipeline never parses; just stores verbatim.
      assert isinstance(r.cursor, str)
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_base.py -v`. 예상: `ImportError: cannot import name 'JobProgress'`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/base.py`에 추가:

  ```python
  import uuid


  @dataclass
  class JobProgress:
      discovered: int = 0
      filtered_out: int = 0
      redacted: int = 0
      embedded: int = 0
      stored: int = 0
      skipped_existing: int = 0
      errors: int = 0
      tokens_consumed: int = 0
      last_cursor: str | None = None


  @dataclass(frozen=True)
  class JobReport:
      job_id: uuid.UUID
      org_id: uuid.UUID
      source_kind: str
      dry_run: bool
      estimated_count: int
      estimated_tokens: int
      indexed_count: int
      skipped: dict[str, int] = field(default_factory=dict)
      errors: int = 0
      started_at: datetime | None = None
      finished_at: datetime | None = None
      progress: JobProgress = field(default_factory=JobProgress)
      sample_titles: list[str] = field(default_factory=list)
      budget_hit: bool = False
      cursor: str | None = None
  ```

  `__init__.py` export 갱신: `from breadmind.kb.backfill.base import BackfillItem, JobProgress, JobReport`.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_base.py -v`. 예상: 8 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/base.py src/breadmind/kb/backfill/__init__.py tests/kb/backfill/test_base.py && git commit -m "feat(kb/backfill): add JobProgress and JobReport dataclasses with opaque cursor"`

---

## Task 4: BackfillJob ABC + cursor_of/instance_id_of + Skipped 예외

**Files:** Modify `src/breadmind/kb/backfill/base.py`. Modify `tests/kb/backfill/test_base.py`.

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  import uuid
  from datetime import datetime, timezone
  from collections.abc import AsyncIterator
  from breadmind.kb.backfill.base import BackfillJob, BackfillItem, Skipped


  class _Concrete(BackfillJob):
      source_kind = "slack_msg"
      async def prepare(self) -> None: ...
      async def discover(self) -> AsyncIterator[BackfillItem]:
          if False:
              yield  # type: ignore[unreachable]
      def filter(self, item: BackfillItem) -> bool:
          return True
      def instance_id_of(self, source_filter: dict) -> str:
          return "T1"


  def test_backfill_job_cannot_instantiate_abstract():
      with pytest.raises(TypeError):
          BackfillJob(  # type: ignore[abstract]
              org_id=uuid.uuid4(), source_filter={}, since=datetime.now(timezone.utc),
              until=datetime.now(timezone.utc), dry_run=True, token_budget=1)


  def test_backfill_job_concrete_constructs():
      job = _Concrete(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=500_000)
      assert job.source_kind == "slack_msg"
      assert job.instance_id_of({}) == "T1"


  def test_cursor_of_default_returns_native_id():
      job = _Concrete(
          org_id=uuid.uuid4(), source_filter={}, since=datetime.now(timezone.utc),
          until=datetime.now(timezone.utc), dry_run=True, token_budget=1)
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="X1", source_uri="u",
          source_created_at=datetime.now(timezone.utc),
          source_updated_at=datetime.now(timezone.utc),
          title="t", body="b", author=None)
      assert job.cursor_of(item) == "X1"


  def test_skipped_exception_carries_reason():
      e = Skipped("acl_lock")
      assert e.reason == "acl_lock"
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_base.py -v -k "backfill_job or cursor_of or skipped_exception"`. 예상: `ImportError: cannot import name 'BackfillJob'`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/base.py`에 추가:

  ```python
  import abc
  from collections.abc import AsyncIterator
  from typing import ClassVar


  class Skipped(Exception):
      """Raised inside discover() to signal a per-item skip with a reason key.

      The runner catches this, increments JobReport.skipped[reason] by 1,
      and continues. Adapters MAY use this instead of (or in addition to)
      filter() returning False with extra["_skip_reason"]."""

      def __init__(self, reason: str):
          super().__init__(reason)
          self.reason = reason


  class BackfillJob(abc.ABC):
      source_kind: ClassVar[str] = ""

      def __init__(
          self,
          *,
          org_id: uuid.UUID,
          source_filter: dict[str, Any],
          since: datetime,
          until: datetime,
          dry_run: bool,
          token_budget: int,
          config: dict[str, Any] | None = None,
      ) -> None:
          self.org_id = org_id
          self.source_filter = source_filter
          self.since = since
          self.until = until
          self.dry_run = dry_run
          self.token_budget = token_budget
          self.config = config or {}

      @abc.abstractmethod
      async def prepare(self) -> None: ...

      @abc.abstractmethod
      def discover(self) -> AsyncIterator[BackfillItem]: ...

      @abc.abstractmethod
      def filter(self, item: BackfillItem) -> bool: ...

      @abc.abstractmethod
      def instance_id_of(self, source_filter: dict[str, Any]) -> str: ...

      async def teardown(self) -> None:
          return None

      def cursor_of(self, item: BackfillItem) -> str:
          return item.source_native_id
  ```

  `__init__.py`에 `BackfillJob`, `Skipped` 추가.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_base.py -v`. 예상: 12 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/base.py src/breadmind/kb/backfill/__init__.py tests/kb/backfill/test_base.py && git commit -m "feat(kb/backfill): add BackfillJob ABC with cursor_of/instance_id_of and Skipped exception"`

---

## Task 5: HourlyPageBudget instance-keyed 확장

**Files:** Modify `src/breadmind/kb/connectors/rate_limit.py`. Create `tests/kb/backfill/test_rate_limit_instance.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_rate_limit_instance.py`:

  ```python
  from __future__ import annotations
  import uuid
  import pytest
  from breadmind.kb.connectors.rate_limit import (
      HourlyPageBudget, BudgetExceeded,
  )


  async def test_legacy_org_only_key_still_works():
      """Backwards compat: passing only project_id preserves existing behaviour."""
      b = HourlyPageBudget(limit=2)
      pid = uuid.uuid4()
      await b.consume(pid, count=1)
      await b.consume(pid, count=1)
      with pytest.raises(BudgetExceeded):
          await b.consume(pid, count=1)


  async def test_instance_keyed_two_orgs_one_workspace_share_dim():
      b = HourlyPageBudget(limit=2)
      org_a, org_b = uuid.uuid4(), uuid.uuid4()
      await b.consume(org_a, count=2, instance_id="T1")
      # Different org, same workspace — independent budgets.
      await b.consume(org_b, count=2, instance_id="T1")
      with pytest.raises(BudgetExceeded):
          await b.consume(org_a, count=1, instance_id="T1")


  async def test_instance_keyed_one_org_two_workspaces_separate_budgets():
      b = HourlyPageBudget(limit=2)
      org = uuid.uuid4()
      await b.consume(org, count=2, instance_id="T1")
      # Same org, different workspace — independent budget.
      await b.consume(org, count=2, instance_id="T2")
      with pytest.raises(BudgetExceeded):
          await b.consume(org, count=1, instance_id="T1")
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_rate_limit_instance.py -v`. 예상: `TypeError: consume() got an unexpected keyword argument 'instance_id'`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/connectors/rate_limit.py`에 키 차원 추가:

  ```python
  # _windows: dict 키를 (project_id, instance_id|None) 튜플로 변경.
  _windows: dict[tuple[uuid.UUID, str | None], _Window] = field(default_factory=dict)

  async def consume(
      self,
      project_id: uuid.UUID,
      count: int = 1,
      *,
      instance_id: str | None = None,
  ) -> None:
      key = (project_id, instance_id)
      t = self.now()
      window = self._windows.get(key)
      if window is None or t - window.start >= 3600.0:
          window = _Window(start=t, count=0)
          self._windows[key] = window
      if window.count + count > self.limit:
          raise BudgetExceeded(
              f"project {project_id} (instance={instance_id}) exceeded "
              f"hourly page budget ({window.count}+{count} > {self.limit})"
          )
      window.count += count

  def reset(self, project_id: uuid.UUID, instance_id: str | None = None) -> None:
      self._windows.pop((project_id, instance_id), None)
  ```

  기존 호출자 (Confluence connector)는 `instance_id=None` 기본값으로 무수정 동작.

- [ ] **Step 4: 통과 확인** —
  - `python -m pytest tests/kb/backfill/test_rate_limit_instance.py -v` — 3 pass.
  - `python -m pytest tests/kb/connectors/test_rate_limit.py -v` — 기존 회귀 통과.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/connectors/rate_limit.py tests/kb/backfill/test_rate_limit_instance.py && git commit -m "feat(kb): extend HourlyPageBudget with (org_id, instance_id) dimension"`

---

## Task 6: OrgMonthlyBudget tracker

**Files:** Create `src/breadmind/kb/backfill/budget.py`. Create `tests/kb/backfill/test_budget.py`. Create `tests/kb/backfill/conftest.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/conftest.py` 먼저 (`mem_backfill_db` fixture: testcontainers Postgres + 010 마이그레이션 + `org_projects` 한 행 시드). `tests/kb/backfill/test_budget.py`:

  ```python
  from __future__ import annotations
  import uuid
  from datetime import date
  import pytest
  from breadmind.kb.backfill.budget import (
      OrgMonthlyBudget, OrgMonthlyBudgetExceeded,
  )

  pytestmark = pytest.mark.asyncio


  async def test_charge_first_time_creates_row(mem_backfill_db, seeded_org):
      b = OrgMonthlyBudget(db=mem_backfill_db, ceiling=1_000_000)
      remaining = await b.charge(org_id=seeded_org, tokens=100,
                                 period=date(2026, 4, 1))
      assert remaining == 999_900
      row = await mem_backfill_db.fetchrow(
          "SELECT tokens_used, tokens_ceiling FROM kb_backfill_org_budget "
          "WHERE org_id=$1 AND period_month=$2", seeded_org, date(2026, 4, 1))
      assert row["tokens_used"] == 100 and row["tokens_ceiling"] == 1_000_000


  async def test_charge_accumulates_within_month(mem_backfill_db, seeded_org):
      b = OrgMonthlyBudget(db=mem_backfill_db, ceiling=1_000)
      await b.charge(seeded_org, 400, period=date(2026, 4, 1))
      remaining = await b.charge(seeded_org, 300, period=date(2026, 4, 1))
      assert remaining == 300


  async def test_charge_raises_when_exceeded(mem_backfill_db, seeded_org):
      b = OrgMonthlyBudget(db=mem_backfill_db, ceiling=500)
      await b.charge(seeded_org, 400, period=date(2026, 4, 1))
      with pytest.raises(OrgMonthlyBudgetExceeded):
          await b.charge(seeded_org, 200, period=date(2026, 4, 1))


  async def test_remaining_returns_ceiling_when_no_row(mem_backfill_db, seeded_org):
      b = OrgMonthlyBudget(db=mem_backfill_db, ceiling=10_000)
      assert await b.remaining(seeded_org, period=date(2026, 4, 1)) == 10_000
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_budget.py -v`. 예상: `ModuleNotFoundError: breadmind.kb.backfill.budget`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/budget.py`:

  ```python
  """Per-org monthly token ceiling for backfill (decision P1)."""
  from __future__ import annotations
  import uuid
  from dataclasses import dataclass
  from datetime import date


  class OrgMonthlyBudgetExceeded(Exception):
      """Raised when charge() would push tokens_used above tokens_ceiling."""


  @dataclass
  class OrgMonthlyBudget:
      db: object  # asyncpg.Connection / Pool
      ceiling: int  # default tokens_ceiling for new rows

      async def charge(
          self, org_id: uuid.UUID, tokens: int, *, period: date,
      ) -> int:
          """Atomic upsert + check. Returns remaining tokens after charge."""
          row = await self.db.fetchrow(
              """
              INSERT INTO kb_backfill_org_budget
                  (org_id, period_month, tokens_used, tokens_ceiling)
              VALUES ($1, $2, $3, $4)
              ON CONFLICT (org_id, period_month) DO UPDATE
                  SET tokens_used = kb_backfill_org_budget.tokens_used + EXCLUDED.tokens_used,
                      updated_at = now()
              RETURNING tokens_used, tokens_ceiling
              """,
              org_id, period, tokens, self.ceiling,
          )
          used, ceiling = row["tokens_used"], row["tokens_ceiling"]
          if used > ceiling:
              raise OrgMonthlyBudgetExceeded(
                  f"org {org_id} {period:%Y-%m} exceeded monthly token "
                  f"ceiling ({used}/{ceiling})"
              )
          return ceiling - used

      async def remaining(self, org_id: uuid.UUID, *, period: date) -> int:
          row = await self.db.fetchrow(
              "SELECT tokens_used, tokens_ceiling FROM kb_backfill_org_budget "
              "WHERE org_id=$1 AND period_month=$2", org_id, period)
          if row is None:
              return self.ceiling
          return row["tokens_ceiling"] - row["tokens_used"]
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_budget.py -v`. 예상: 4 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/budget.py tests/kb/backfill/test_budget.py tests/kb/backfill/conftest.py && git commit -m "feat(kb/backfill): add OrgMonthlyBudget tracker (decision P1)"`

---

## Task 7: BackfillRunner — prepare/ACL snapshot + dry-run skeleton

**Files:** Create `src/breadmind/kb/backfill/runner.py`. Create `tests/kb/backfill/test_runner.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_runner.py`:

  ```python
  from __future__ import annotations
  import uuid
  from collections.abc import AsyncIterator
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.base import BackfillItem, BackfillJob
  from breadmind.kb.backfill.runner import BackfillRunner

  pytestmark = pytest.mark.asyncio


  class _StubJob(BackfillJob):
      source_kind = "slack_msg"

      def __init__(self, items, **kw):
          super().__init__(**kw)
          self._items = items
          self.prepared = False

      async def prepare(self) -> None:
          self.prepared = True

      async def discover(self) -> AsyncIterator[BackfillItem]:
          for it in self._items:
              yield it

      def filter(self, item: BackfillItem) -> bool:
          return True

      def instance_id_of(self, source_filter):
          return "T1"


  def _item(i: int) -> BackfillItem:
      ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
      return BackfillItem(
          source_kind="slack_msg", source_native_id=f"x{i}",
          source_uri="u", source_created_at=ts, source_updated_at=ts,
          title=f"t{i}", body="hello world", author="U1")


  async def test_runner_calls_prepare_before_discover(mem_backfill_db, seeded_org):
      job = _StubJob(
          [_item(0)], org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=10_000)
      runner = BackfillRunner(db=mem_backfill_db, redactor=None, embedder=None)
      await runner.run(job)
      assert job.prepared is True


  async def test_dry_run_skips_redact_embed_store(mem_backfill_db, seeded_org):
      items = [_item(i) for i in range(3)]
      job = _StubJob(
          items, org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=10_000)
      runner = BackfillRunner(db=mem_backfill_db, redactor=None, embedder=None)
      report = await runner.run(job)
      assert report.dry_run is True
      assert report.estimated_count == 3
      assert report.estimated_tokens == sum(len("hello world") // 4 for _ in items)
      assert report.indexed_count == 0
      assert len(report.sample_titles) == 3
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_runner.py -v`. 예상: `ModuleNotFoundError: breadmind.kb.backfill.runner`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/runner.py`:

  ```python
  """Backfill pipeline orchestrator."""
  from __future__ import annotations
  import uuid
  from dataclasses import dataclass, field
  from datetime import datetime, timezone
  from breadmind.kb.backfill.base import (
      BackfillItem, BackfillJob, JobProgress, JobReport, Skipped,
  )


  _SAMPLE_LIMIT = 10


  @dataclass
  class BackfillRunner:
      db: object
      redactor: object | None
      embedder: object | None
      org_budget: object | None = None  # OrgMonthlyBudget; None disables P1
      checkpoint_every_n: int = 50
      checkpoint_every_seconds: float = 30.0
      error_ratio_threshold: float = 0.10
      error_ratio_min_items: int = 200

      async def run(self, job: BackfillJob) -> JobReport:
          await job.prepare()
          progress = JobProgress()
          skipped: dict[str, int] = {}
          sample_titles: list[str] = []
          started_at = datetime.now(timezone.utc)

          last_item: BackfillItem | None = None
          async for item in job.discover():
              progress.discovered += 1
              if not job.filter(item):
                  reason = item.extra.get("_skip_reason", "filtered")
                  skipped[reason] = skipped.get(reason, 0) + 1
                  progress.filtered_out += 1
                  continue
              # Token estimate (cheap len/4 heuristic per spec §4).
              progress.tokens_consumed += len(item.body) // 4
              if len(sample_titles) < _SAMPLE_LIMIT:
                  sample_titles.append(item.title)
              if job.dry_run:
                  last_item = item
                  continue
              # Real-run pipeline lands in Task 8/9.
              raise NotImplementedError(
                  "real-run pipeline lands in Task 8/9")

          await job.teardown()
          finished_at = datetime.now(timezone.utc)
          return JobReport(
              job_id=uuid.uuid4(),
              org_id=job.org_id,
              source_kind=job.source_kind,
              dry_run=job.dry_run,
              estimated_count=progress.discovered - progress.filtered_out,
              estimated_tokens=progress.tokens_consumed,
              indexed_count=0,
              skipped=skipped,
              errors=progress.errors,
              started_at=started_at,
              finished_at=finished_at,
              progress=progress,
              sample_titles=sample_titles,
              budget_hit=False,
              cursor=job.cursor_of(last_item) if last_item else None,
          )
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_runner.py -v -k "prepare or dry_run_skips"`. 예상: 2 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/runner.py tests/kb/backfill/test_runner.py && git commit -m "feat(kb/backfill): BackfillRunner skeleton with prepare + dry-run estimation"`

---

## Task 8: Runner — redact/embed/store + token_budget gate + 10% error abort

**Files:** Modify `src/breadmind/kb/backfill/runner.py`, `tests/kb/backfill/test_runner.py`. Modify `tests/kb/backfill/conftest.py` (FakeRedactor / FakeEmbedder).

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  async def test_runner_full_pipeline_inserts_org_knowledge(
      mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
  ):
      items = [_item(i) for i in range(3)]
      job = _StubJob(
          items, org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10_000)
      runner = BackfillRunner(
          db=mem_backfill_db, redactor=fake_redactor, embedder=fake_embedder)
      report = await runner.run(job)
      assert report.indexed_count == 3
      rows = await mem_backfill_db.fetch(
          "SELECT source_native_id FROM org_knowledge "
          "WHERE project_id=$1 AND source_kind='slack_msg' "
          "ORDER BY source_native_id", seeded_org)
      assert [r["source_native_id"] for r in rows] == ["x0", "x1", "x2"]


  async def test_runner_token_budget_halts_midway(
      mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
  ):
      items = [_item(i) for i in range(20)]
      # Each body "hello world" is 11 chars -> 2 tokens. budget=4 stops at item 3.
      job = _StubJob(
          items, org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=4)
      runner = BackfillRunner(
          db=mem_backfill_db, redactor=fake_redactor, embedder=fake_embedder)
      report = await runner.run(job)
      assert report.budget_hit is True
      assert report.indexed_count < 20


  async def test_runner_aborts_on_10pct_error_rate(
      mem_backfill_db, seeded_org, fake_redactor, exploding_embedder,
  ):
      """exploding_embedder raises on every encode after item 0."""
      items = [_item(i) for i in range(250)]
      job = _StubJob(
          items, org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=999_999_999)
      runner = BackfillRunner(
          db=mem_backfill_db, redactor=fake_redactor,
          embedder=exploding_embedder)
      with pytest.raises(RuntimeError, match="error rate"):
          await runner.run(job)
  ```

  `conftest.py` — `fake_redactor` (passes through, no-op `abort_if_secrets`, returns `(text, "map-id")`); `fake_embedder` (returns deterministic 384-dim float list); `exploding_embedder` (raises after first item).

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_runner.py -v -k "full_pipeline or token_budget or 10pct"`. 예상: NotImplementedError.

- [ ] **Step 3: 구현** — `runner.py`의 dry-run continue 분기 자리 교체:

  ```python
  # token_budget gate: spec §4 — runner increments BEFORE embed using
  # len(body)//4 estimate; bails when >= token_budget.
  if progress.tokens_consumed >= job.token_budget:
      budget_hit = True
      break
  try:
      await self.redactor.abort_if_secrets(item.body)
      redacted_body, _map_id = await self.redactor.redact(
          item.body, session_id=str(job.org_id))
      progress.redacted += 1
  except Exception as e:
      if e.__class__.__name__ == "SecretDetected":
          skipped["redact_dropped"] = skipped.get("redact_dropped", 0) + 1
          continue
      progress.errors += 1
      _maybe_abort(progress)
      continue
  try:
      vec = await self.embedder.encode(redacted_body)
      progress.embedded += 1
  except Exception:
      progress.errors += 1
      _maybe_abort(progress)
      continue
  # Pseudonymise author (P3): Slack mention pattern from kb/redactor.
  author = _pseudonymise_author(item.author)
  try:
      await self.db.execute(
          """
          INSERT INTO org_knowledge
              (project_id, body, source_kind, source_native_id,
               source_uri, source_created_at, source_updated_at,
               parent_ref, author)
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
          ON CONFLICT (project_id, source_kind, source_native_id)
              WHERE source_native_id IS NOT NULL AND superseded_by IS NULL
              DO NOTHING
          """,
          job.org_id, redacted_body, item.source_kind,
          item.source_native_id, item.source_uri,
          item.source_created_at, item.source_updated_at,
          item.parent_ref, author,
      )
      progress.stored += 1
      indexed_count += 1
  except Exception:
      progress.errors += 1
      _maybe_abort(progress)
  last_item = item
  ```

  helper:

  ```python
  def _maybe_abort(self, progress: JobProgress) -> None:
      if progress.discovered < self.error_ratio_min_items:
          return
      if progress.errors > self.error_ratio_threshold * progress.discovered:
          raise RuntimeError(
              f"error rate {progress.errors}/{progress.discovered} "
              f"exceeds {self.error_ratio_threshold:.0%} threshold")

  def _pseudonymise_author(value: str | None) -> str | None:
      if not value:
          return value
      import re
      # Reuse Slack mention pattern from kb/redactor; bare Uxxxx/Wxxxx
      # → "<USER_n>" placeholder per decision P3 in spec §11.
      if re.match(r"^[UW][A-Z0-9]{6,}$", value):
          import hashlib
          return f"<USER_{hashlib.sha1(value.encode()).hexdigest()[:8]}>"
      return value
  ```

  최종 `JobReport.indexed_count = indexed_count`, `budget_hit = budget_hit`. `body` 컬럼이 존재하지 않으면 ALTER TABLE 보완 (현재 spec scope이 아니므로 mem_backfill_db fixture가 필요한 컬럼 보장).

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_runner.py -v`. 예상: 5 pass (Task 7 의 2 + 새 3).

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/runner.py tests/kb/backfill/test_runner.py tests/kb/backfill/conftest.py && git commit -m "feat(kb/backfill): runner redact/embed/store with token_budget gate and 10% error abort"`

---

## Task 9: Runner — kb_backfill_jobs 체크포인트 (every 50 items / 30s) + resume

**Files:** Create `src/breadmind/kb/backfill/checkpoint.py`. Modify `runner.py`. Create `tests/kb/backfill/test_checkpoint.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_checkpoint.py`:

  ```python
  from __future__ import annotations
  import uuid
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.checkpoint import (
      JobCheckpointer, load_resume_cursor,
  )

  pytestmark = pytest.mark.asyncio


  async def test_checkpointer_creates_pending_row(mem_backfill_db, seeded_org):
      cp = JobCheckpointer(db=mem_backfill_db)
      job_id = await cp.start(
          org_id=seeded_org, source_kind="slack_msg",
          source_filter={"channels": ["C1"]}, instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=500_000, created_by="alice")
      row = await mem_backfill_db.fetchrow(
          "SELECT status, instance_id FROM kb_backfill_jobs WHERE id=$1", job_id)
      assert row["status"] == "running"
      assert row["instance_id"] == "T1"


  async def test_checkpoint_writes_cursor_and_progress(mem_backfill_db, seeded_org):
      cp = JobCheckpointer(db=mem_backfill_db)
      job_id = await cp.start(
          org_id=seeded_org, source_kind="slack_msg", source_filter={},
          instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10, created_by="t")
      await cp.checkpoint(
          job_id=job_id, cursor="1730000000:C1:1.0",
          progress={"discovered": 50}, skipped={"signal_filter_short": 3})
      row = await mem_backfill_db.fetchrow(
          "SELECT last_cursor, progress_json, skipped_json "
          "FROM kb_backfill_jobs WHERE id=$1", job_id)
      assert row["last_cursor"] == "1730000000:C1:1.0"


  async def test_load_resume_cursor_returns_last_cursor(mem_backfill_db, seeded_org):
      cp = JobCheckpointer(db=mem_backfill_db)
      job_id = await cp.start(
          org_id=seeded_org, source_kind="slack_msg", source_filter={},
          instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10, created_by="t")
      await cp.checkpoint(job_id=job_id, cursor="X", progress={}, skipped={})
      assert await load_resume_cursor(mem_backfill_db, job_id) == "X"


  async def test_runner_writes_checkpoint_every_50_items(
      mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
  ):
      from breadmind.kb.backfill.runner import BackfillRunner
      from tests.kb.backfill.test_runner import _StubJob, _item
      items = [_item(i) for i in range(120)]
      job = _StubJob(
          items, org_id=seeded_org, source_filter={},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10**9)
      runner = BackfillRunner(
          db=mem_backfill_db, redactor=fake_redactor,
          embedder=fake_embedder, checkpoint_every_n=50)
      await runner.run(job)
      row = await mem_backfill_db.fetchrow(
          "SELECT status, last_cursor FROM kb_backfill_jobs "
          "ORDER BY created_at DESC LIMIT 1")
      assert row["status"] == "completed"
      assert row["last_cursor"] is not None
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_checkpoint.py -v`. 예상: `ModuleNotFoundError: breadmind.kb.backfill.checkpoint`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/checkpoint.py`:

  ```python
  from __future__ import annotations
  import json
  import uuid
  from dataclasses import dataclass
  from datetime import datetime


  @dataclass
  class JobCheckpointer:
      db: object

      async def start(
          self, *, org_id: uuid.UUID, source_kind: str,
          source_filter: dict, instance_id: str,
          since: datetime, until: datetime, dry_run: bool,
          token_budget: int, created_by: str,
      ) -> uuid.UUID:
          row = await self.db.fetchrow(
              """
              INSERT INTO kb_backfill_jobs
                  (org_id, source_kind, source_filter, instance_id,
                   since_ts, until_ts, dry_run, token_budget,
                   status, started_at, created_by)
              VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8,
                      'running', now(), $9)
              RETURNING id
              """,
              org_id, source_kind, json.dumps(source_filter), instance_id,
              since, until, dry_run, token_budget, created_by,
          )
          return row["id"]

      async def checkpoint(
          self, *, job_id: uuid.UUID, cursor: str | None,
          progress: dict, skipped: dict[str, int],
      ) -> None:
          await self.db.execute(
              """
              UPDATE kb_backfill_jobs
                  SET last_cursor = $2,
                      progress_json = $3::jsonb,
                      skipped_json  = $4::jsonb
                WHERE id = $1
              """,
              job_id, cursor, json.dumps(progress), json.dumps(skipped),
          )

      async def finish(
          self, *, job_id: uuid.UUID, status: str, error: str | None = None,
      ) -> None:
          await self.db.execute(
              """
              UPDATE kb_backfill_jobs
                  SET status = $2, finished_at = now(), error = $3
                WHERE id = $1
              """,
              job_id, status, error,
          )


  async def load_resume_cursor(db, job_id: uuid.UUID) -> str | None:
      row = await db.fetchrow(
          "SELECT last_cursor FROM kb_backfill_jobs WHERE id=$1", job_id)
      return row["last_cursor"] if row else None
  ```

  Runner 통합: `runner.run` 진입 시 `JobCheckpointer.start()` 호출, 매 `discovered % checkpoint_every_n == 0` 또는 `time.monotonic() - last_cp_t >= checkpoint_every_seconds` 일 때 `checkpoint()`, 정상 종료 시 `finish(status='completed')`, `BudgetExceeded`/`OrgMonthlyBudgetExceeded` 시 `finish(status='paused')`, 10% 에러 abort 시 `finish(status='failed', error=...)`.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_checkpoint.py -v`. 예상: 4 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/checkpoint.py src/breadmind/kb/backfill/runner.py tests/kb/backfill/test_checkpoint.py && git commit -m "feat(kb/backfill): JobCheckpointer with 50-item/30s cadence and runner integration"`

---

## Task 10: SlackBackfillAdapter.prepare() — ACL snapshot + archive 사전 체크 (P4 fail-closed)

**Files:** Create `src/breadmind/kb/backfill/slack.py`. Create `tests/kb/backfill/test_slack_discover.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_slack_discover.py` (앞부분):

  ```python
  from __future__ import annotations
  import uuid
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.slack import SlackBackfillAdapter

  pytestmark = pytest.mark.asyncio


  class FakeSlackSession:
      def __init__(self, payloads: dict[str, list[dict]]):
          self._payloads = payloads
          self.calls: list[tuple[str, dict]] = []

      async def call(self, method: str, **params):
          self.calls.append((method, params))
          return self._payloads[method].pop(0)


  class FakeVault:
      async def retrieve(self, ref: str) -> str | None:
          return "xoxb-token"


  async def test_prepare_snapshots_membership_and_team_id():
      session = FakeSlackSession({
          "auth.test": [{"ok": True, "team_id": "T123"}],
          "conversations.info": [
              {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
          "conversations.members": [
              {"ok": True, "members": ["U1", "U2"], "response_metadata": {}}],
      })
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=1, vault=FakeVault(),
          credentials_ref="slack:org", session=session)
      await job.prepare()
      assert job._membership_snapshot == frozenset({"U1", "U2"})
      assert job._team_id == "T123"


  async def test_prepare_fail_closed_on_archived_channel():
      session = FakeSlackSession({
          "auth.test": [{"ok": True, "team_id": "T1"}],
          "conversations.info": [
              {"ok": True, "channel": {"id": "C1", "is_archived": True}}],
      })
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=1, vault=FakeVault(),
          credentials_ref="slack:org", session=session)
      with pytest.raises(PermissionError, match="archived"):
          await job.prepare()


  def test_instance_id_of_returns_team_id():
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=1, vault=FakeVault(),
          credentials_ref="slack:org", session=None)
      job._team_id = "T999"
      assert job.instance_id_of(job.source_filter) == "T999"
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_slack_discover.py::test_prepare_snapshots_membership_and_team_id -v`. 예상: `ModuleNotFoundError: breadmind.kb.backfill.slack`.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/slack.py` 신규:

  ```python
  """Slack backfill adapter — conversations.history + conversations.replies."""
  from __future__ import annotations
  import re
  import uuid
  from collections.abc import AsyncIterator
  from datetime import datetime, timezone
  from typing import Any, ClassVar

  from breadmind.kb.backfill.base import (
      BackfillItem, BackfillJob, Skipped,
  )

  _BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800)
  _SLACK_USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{6,}$")


  class SlackBackfillAdapter(BackfillJob):
      source_kind: ClassVar[str] = "slack_msg"

      def __init__(
          self, *, vault, credentials_ref: str,
          session=None, **kw,
      ) -> None:
          super().__init__(**kw)
          self._vault = vault
          self._credentials_ref = credentials_ref
          self._session = session
          self._membership_snapshot: frozenset[str] = frozenset()
          self._team_id: str = ""
          self._archived_channels: set[str] = set()
          self._channel_names: dict[str, str] = {}

      def instance_id_of(self, source_filter: dict[str, Any]) -> str:
          if not self._team_id:
              raise RuntimeError("instance_id_of called before prepare()")
          return self._team_id

      async def prepare(self) -> None:
          channels = self.source_filter.get("channels") or []
          if not channels:
              raise PermissionError("Slack source_filter.channels required")
          auth = await self._session.call("auth.test")
          if not auth.get("ok"):
              raise PermissionError(f"Slack auth.test failed: {auth}")
          self._team_id = auth["team_id"]
          members: set[str] = set()
          for cid in channels:
              info = await self._session.call("conversations.info", channel=cid)
              if not info.get("ok"):
                  raise PermissionError(
                      f"channel {cid} info failed: {info}")
              ch = info["channel"]
              if ch.get("is_archived"):
                  raise PermissionError(
                      f"channel {cid} archived since dry-run; "
                      "re-run dry-run to refresh and try again.")
              # conversations.members pagination
              cursor: str | None = None
              while True:
                  payload = await self._session.call(
                      "conversations.members", channel=cid, cursor=cursor)
                  members.update(payload.get("members", []))
                  cursor = (payload.get("response_metadata") or {}).get(
                      "next_cursor")
                  if not cursor:
                      break
          self._membership_snapshot = frozenset(members)

      def filter(self, item: BackfillItem) -> bool:
          # Stub — full heuristics in Task 12.
          return True

      async def discover(self) -> AsyncIterator[BackfillItem]:
          # Stub — implementation in Task 11.
          if False:
              yield  # type: ignore[unreachable]
  ```

  `__init__.py`에 `SlackBackfillAdapter` export 추가.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_slack_discover.py -v -k "prepare or instance_id_of"`. 예상: 3 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/slack.py src/breadmind/kb/backfill/__init__.py tests/kb/backfill/test_slack_discover.py && git commit -m "feat(kb/backfill): SlackBackfillAdapter prepare with ACL snapshot and P4 fail-closed archive check"`

---

## Task 11: SlackBackfillAdapter.discover() — conversations.history + replies + 스레드 롤업 + 429 retry

**Files:** Modify `src/breadmind/kb/backfill/slack.py`. Modify `tests/kb/backfill/test_slack_discover.py`.

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  async def test_discover_yields_top_level_messages_in_window():
      session = FakeSlackSession({
          "auth.test": [{"ok": True, "team_id": "T1"}],
          "conversations.info": [
              {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
          "conversations.members": [
              {"ok": True, "members": ["U1"], "response_metadata": {}}],
          "conversations.history": [
              {"ok": True, "messages": [
                  {"ts": "1735689600.0", "user": "U1",
                   "text": "hello", "permalink": "https://x"},
                  {"ts": "1735776000.0", "user": "U1",
                   "text": "world", "permalink": "https://y"},
              ], "has_more": False}],
      })
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2025, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=10**9, vault=FakeVault(),
          credentials_ref="slack:o", session=session)
      await job.prepare()
      out = [it async for it in job.discover()]
      assert len(out) == 2
      assert out[0].source_native_id == "C1:1735689600.0"


  async def test_discover_threads_collapse_to_one_item():
      replies_payload = {"ok": True, "messages": [
          {"ts": "1.0", "thread_ts": "1.0", "text": "Q?", "user": "U1"},
          {"ts": "1.1", "thread_ts": "1.0", "text": "A.", "user": "U2"},
      ], "has_more": False}
      session = FakeSlackSession({
          "auth.test": [{"ok": True, "team_id": "T1"}],
          "conversations.info": [
              {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
          "conversations.members": [
              {"ok": True, "members": ["U1", "U2"], "response_metadata": {}}],
          "conversations.history": [{"ok": True, "messages": [
              {"ts": "1.0", "thread_ts": "1.0", "reply_count": 1,
               "user": "U1", "text": "Q?"}], "has_more": False}],
          "conversations.replies": [replies_payload],
      })
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={
              "channels": ["C1"], "include_threads": True},
          since=datetime(1970, 1, 1, tzinfo=timezone.utc),
          until=datetime(2099, 1, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=10**9, vault=FakeVault(),
          credentials_ref="slack:o", session=session)
      await job.prepare()
      out = [it async for it in job.discover()]
      assert len(out) == 1
      assert out[0].source_native_id == "C1:1.0:thread"
      assert "Q?" in out[0].body and "A." in out[0].body


  async def test_discover_retries_on_429_with_retry_after():
      session = FakeSlackSession({
          "auth.test": [{"ok": True, "team_id": "T1"}],
          "conversations.info": [
              {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
          "conversations.members": [
              {"ok": True, "members": [], "response_metadata": {}}],
          "conversations.history": [
              {"ok": False, "error": "ratelimited",
               "_status": 429, "_retry_after": 0},  # interpreted as 0s sleep
              {"ok": True, "messages": [], "has_more": False}],
      })
      job = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=1, vault=FakeVault(),
          credentials_ref="slack:o", session=session)
      await job.prepare()
      _ = [it async for it in job.discover()]
      methods = [c[0] for c in session.calls]
      assert methods.count("conversations.history") == 2
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_slack_discover.py -v -k "discover_yields or threads_collapse or 429"`. 예상: empty iterator (assertion fails).

- [ ] **Step 3: 구현** — `slack.py` `discover()` 본문:

  ```python
  async def discover(self) -> AsyncIterator[BackfillItem]:
      since_ts = self.since.timestamp()
      until_ts = self.until.timestamp()
      include_threads = self.source_filter.get("include_threads", True)
      for cid in self.source_filter["channels"]:
          cursor: str | None = None
          while True:
              params: dict[str, Any] = {
                  "channel": cid, "limit": 200,
                  "oldest": str(since_ts), "latest": str(until_ts),
              }
              if cursor:
                  params["cursor"] = cursor
              payload = await self._call_with_retry(
                  "conversations.history", **params)
              for msg in payload.get("messages", []):
                  ts = float(msg["ts"])
                  if ts < since_ts or ts >= until_ts:
                      continue
                  if include_threads and msg.get("thread_ts") == msg["ts"] \
                          and (msg.get("reply_count") or 0) > 0:
                      yield await self._build_thread_item(cid, msg)
                  else:
                      yield self._build_top_level_item(cid, msg)
              if not payload.get("has_more"):
                  break
              cursor = (payload.get("response_metadata") or {}).get(
                  "next_cursor")
              if not cursor:
                  break

  async def _call_with_retry(self, method: str, **params):
      backoffs = list(_BACKOFF_SECONDS)
      while True:
          payload = await self._session.call(method, **params)
          if payload.get("_status") == 429 or (
                  payload.get("error") == "ratelimited"):
              import asyncio
              wait = int(payload.get("_retry_after") or
                         (backoffs.pop(0) if backoffs else _BACKOFF_SECONDS[-1]))
              await asyncio.sleep(wait)
              continue
          return payload

  def _build_top_level_item(self, cid: str, msg: dict) -> BackfillItem:
      ts = float(msg["ts"])
      created = datetime.fromtimestamp(ts, tz=timezone.utc)
      return BackfillItem(
          source_kind="slack_msg",
          source_native_id=f"{cid}:{msg['ts']}",
          source_uri=msg.get("permalink", f"slack://msg/{cid}/{msg['ts']}"),
          source_created_at=created,
          source_updated_at=datetime.fromtimestamp(
              float(msg.get("edited", {}).get("ts", msg["ts"])), tz=timezone.utc),
          title=f"[#{self._channel_names.get(cid, cid)}] "
                f"{(msg.get('text') or '')[:80]}",
          body=msg.get("text", ""),
          author=msg.get("user") or msg.get("bot_id"),
          parent_ref=None,
          extra={"subtype": msg.get("subtype"),
                 "reaction_count": sum(r.get("count", 0)
                                       for r in msg.get("reactions", []) or []),
                 "reply_count": msg.get("reply_count", 0)},
      )

  async def _build_thread_item(self, cid: str, parent: dict) -> BackfillItem:
      thread_ts = parent["ts"]
      bodies: list[str] = [parent.get("text", "")]
      latest_edit_ts = float(parent["ts"])
      cursor = None
      char_budget = 4000
      while True:
          rp = await self._call_with_retry(
              "conversations.replies", channel=cid,
              ts=thread_ts, limit=200, cursor=cursor)
          for r in rp.get("messages", []):
              if r["ts"] == thread_ts:
                  continue
              ts = float(r["ts"])
              # client-side cut: replies API ignores oldest/latest
              if ts < self.since.timestamp() or ts >= self.until.timestamp():
                  continue
              text = r.get("text", "")
              if sum(len(b) for b in bodies) + len(text) > char_budget:
                  break
              bodies.append(text)
              latest_edit_ts = max(latest_edit_ts, ts)
          if not rp.get("has_more"):
              break
          cursor = (rp.get("response_metadata") or {}).get("next_cursor")
          if not cursor:
              break
      return BackfillItem(
          source_kind="slack_msg",
          source_native_id=f"{cid}:{thread_ts}:thread",
          source_uri=parent.get("permalink",
                                f"slack://msg/{cid}/{thread_ts}"),
          source_created_at=datetime.fromtimestamp(
              float(thread_ts), tz=timezone.utc),
          source_updated_at=datetime.fromtimestamp(
              latest_edit_ts, tz=timezone.utc),
          title=f"[#{self._channel_names.get(cid, cid)}] "
                f"{(parent.get('text') or '')[:80]}",
          body="\n\n".join(bodies),
          author=parent.get("user"),
          parent_ref=None,  # this IS the parent
          extra={"reaction_count": sum(r.get("count", 0)
                                       for r in parent.get("reactions", []) or []),
                 "reply_count": parent.get("reply_count", 0)},
      )
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_slack_discover.py -v`. 예상: 6 tests pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/slack.py tests/kb/backfill/test_slack_discover.py && git commit -m "feat(kb/backfill): Slack discover with history/replies pagination thread roll-up and 429 retry"`

---

## Task 12: SlackBackfillAdapter.filter() — 4 시그널 휴리스틱 + ACL 라벨

**Files:** Modify `src/breadmind/kb/backfill/slack.py`. Create `tests/kb/backfill/test_slack_filter.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_slack_filter.py`:

  ```python
  from __future__ import annotations
  import uuid
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.base import BackfillItem
  from breadmind.kb.backfill.slack import SlackBackfillAdapter


  def _job():
      class _NullVault:
          async def retrieve(self, *_): return None
      j = SlackBackfillAdapter(
          org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=True, token_budget=1, vault=_NullVault(),
          credentials_ref="x", session=None)
      j._membership_snapshot = frozenset({"U1", "U2"})
      return j


  def _it(body: str, **extra) -> BackfillItem:
      ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
      return BackfillItem(
          source_kind="slack_msg", source_native_id="C1:1.0",
          source_uri="u", source_created_at=ts, source_updated_at=ts,
          title="t", body=body, author=extra.pop("author", "U1"),
          extra={"subtype": None, "reaction_count": 1, "reply_count": 0,
                 **extra})


  def test_filter_drops_short_message():
      j = _job()
      it = _it("hi")
      assert j.filter(it) is False
      assert it.extra["_skip_reason"] == "signal_filter_short"


  def test_filter_drops_bot_subtype():
      j = _job()
      it = _it("a long enough body", subtype="bot_message")
      assert j.filter(it) is False
      assert it.extra["_skip_reason"] == "signal_filter_bot"


  def test_filter_drops_zero_engagement_no_thread():
      j = _job()
      it = _it("a long enough body", reaction_count=0, reply_count=0)
      assert j.filter(it) is False
      assert it.extra["_skip_reason"] == "signal_filter_no_engagement"


  def test_filter_drops_pure_mention_only():
      j = _job()
      it = _it("<@U99> <#C00>")
      assert j.filter(it) is False
      assert it.extra["_skip_reason"] == "signal_filter_mention_only"


  def test_filter_keeps_engaged_long_message():
      j = _job()
      it = _it("real recap of postgres tuning", reaction_count=2)
      assert j.filter(it) is True


  def test_filter_acl_lock_label():
      j = _job()
      it = _it("real content here", reaction_count=2, author="U_ALIEN")
      assert j.filter(it) is False
      assert it.extra["_skip_reason"] == "acl_lock"


  def test_filter_thresholds_tunable():
      j = _job()
      j.config = {"min_length": 20, "drop_zero_engagement": False}
      it = _it("short but long enough?")  # 22 chars; reaction=0, reply=0
      assert j.filter(it) is True
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_slack_filter.py -v`. 예상: stub returns True for all → 6 fails.

- [ ] **Step 3: 구현** — `slack.py`의 `filter()` 교체:

  ```python
  _MENTION_RE = re.compile(r"<@[UW][A-Z0-9]+>|<#C[A-Z0-9]+\|?[^>]*>")
  _NON_WORD_RE = re.compile(r"^\W*$", flags=re.UNICODE)

  def filter(self, item: BackfillItem) -> bool:
      cfg = self.config or {}
      min_length = cfg.get("min_length", 5)
      drop_zero_engagement = cfg.get("drop_zero_engagement", True)
      body = (item.body or "").strip()

      # Rule 1: length (after stripping mentions/emoji)
      stripped = self._MENTION_RE.sub("", body).strip()
      if len(stripped) < min_length:
          item.extra["_skip_reason"] = "signal_filter_short"
          return False

      # Rule 2: bot/system subtype
      bot_subtypes = {"bot_message", "channel_join", "channel_leave",
                      "channel_topic", "channel_purpose"}
      if item.extra.get("subtype") in bot_subtypes:
          item.extra["_skip_reason"] = "signal_filter_bot"
          return False

      # Rule 3: no engagement and no thread
      if drop_zero_engagement and item.extra.get("reaction_count", 0) == 0 \
              and item.extra.get("reply_count", 0) == 0:
          item.extra["_skip_reason"] = "signal_filter_no_engagement"
          return False

      # Rule 4: pure mention/emoji
      if not stripped or self._NON_WORD_RE.match(stripped):
          item.extra["_skip_reason"] = "signal_filter_mention_only"
          return False

      # ACL label (no per-item API call): mismatch → skipped["acl_lock"]
      if item.author and _SLACK_USER_ID_RE.match(item.author) \
              and item.author not in self._membership_snapshot:
          item.extra["_skip_reason"] = "acl_lock"
          return False

      return True
  ```

  `_MENTION_RE` 와 `_NON_WORD_RE`는 클래스 레벨 ClassVar로 정의.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_slack_filter.py -v`. 예상: 7 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/slack.py tests/kb/backfill/test_slack_filter.py && git commit -m "feat(kb/backfill): Slack signal heuristics + ACL label per spec §6.4/§6.3a"`

---

## Task 13: SlackBackfillAdapter.cursor_of()

**Files:** Modify `src/breadmind/kb/backfill/slack.py`. Modify `tests/kb/backfill/test_slack_filter.py` (add cursor tests).

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  def test_cursor_of_top_level_format():
      j = _job()
      ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="C1:1735689600.0",
          source_uri="u", source_created_at=ts, source_updated_at=ts,
          title="t", body="b", author="U1")
      cur = j.cursor_of(item)
      # f"{ts_ms}:{channel_id}:{message_ts}"
      assert cur == f"{int(ts.timestamp() * 1000)}:C1:1735689600.0"


  def test_cursor_of_thread_format():
      j = _job()
      ts = datetime(2026, 2, 15, tzinfo=timezone.utc)
      item = BackfillItem(
          source_kind="slack_msg", source_native_id="C1:1.0:thread",
          source_uri="u", source_created_at=ts, source_updated_at=ts,
          title="t", body="b", author="U1")
      cur = j.cursor_of(item)
      assert cur.endswith(":C1:1.0:thread") or cur.endswith(":C1:1.0")
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_slack_filter.py -v -k cursor_of`. 예상: 2 fails (default returns native_id).

- [ ] **Step 3: 구현** — `slack.py`에 `cursor_of` override:

  ```python
  def cursor_of(self, item: BackfillItem) -> str:
      # spec §6.6: f"{ts_ms}:{channel_id}:{message_ts}"
      ts_ms = int(item.source_updated_at.timestamp() * 1000)
      # source_native_id is "<channel_id>:<message_ts>[:thread]"
      return f"{ts_ms}:{item.source_native_id}"

  def _cursor_to_oldest(self, cursor: str) -> str:
      """Reverse: cursor -> Slack `oldest=` (seconds float string)."""
      ts_ms = int(cursor.split(":", 1)[0])
      return f"{ts_ms / 1000:.6f}"
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_slack_filter.py -v -k cursor_of`. 예상: 2 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/slack.py tests/kb/backfill/test_slack_filter.py && git commit -m "feat(kb/backfill): Slack cursor_of monotonic format per spec §6.6"`

---

## Task 14: CLI argparse — `breadmind kb backfill slack ...` 인자

**Files:** Create `src/breadmind/kb/backfill/cli.py`. Modify `src/breadmind/main.py`. Create `tests/kb/backfill/test_cli.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/kb/backfill/test_cli.py`:

  ```python
  from __future__ import annotations
  import pytest
  from breadmind.kb.backfill.cli import build_parser, parse_slack_args


  def test_parser_requires_org_and_channel():
      parser = build_parser()
      with pytest.raises(SystemExit):
          parser.parse_args(["slack"])
      with pytest.raises(SystemExit):
          parser.parse_args(["slack", "--org", "u"])


  def test_parse_slack_args_canonicalises():
      parser = build_parser()
      ns = parser.parse_args([
          "slack", "--org", "00000000-0000-0000-0000-000000000001",
          "--channel", "C1", "--channel", "C2",
          "--since", "2026-01-01", "--until", "2026-04-01",
          "--token-budget", "500000", "--dry-run",
      ])
      assert ns.subcommand == "slack"
      assert ns.channel == ["C1", "C2"]
      assert ns.dry_run is True
      assert ns.token_budget == 500_000


  def test_parse_slack_args_min_length_and_threads_default():
      parser = build_parser()
      ns = parser.parse_args([
          "slack", "--org", "00000000-0000-0000-0000-000000000001",
          "--channel", "C1", "--since", "2026-01-01",
          "--until", "2026-04-01", "--dry-run"])
      assert ns.include_threads is True  # default
      assert ns.min_length == 5  # default


  def test_resume_subcommand_takes_job_id():
      parser = build_parser()
      ns = parser.parse_args(
          ["resume", "00000000-0000-0000-0000-000000000abc"])
      assert ns.subcommand == "resume"


  def test_list_filters_status():
      parser = build_parser()
      ns = parser.parse_args([
          "list", "--org", "00000000-0000-0000-0000-000000000001",
          "--status", "running"])
      assert ns.status == "running"


  def test_cancel_takes_job_id():
      parser = build_parser()
      ns = parser.parse_args(
          ["cancel", "00000000-0000-0000-0000-000000000abc"])
      assert ns.subcommand == "cancel"
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v`. 예상: ModuleNotFoundError.

- [ ] **Step 3: 구현** — `src/breadmind/kb/backfill/cli.py`:

  ```python
  """CLI entrypoint: breadmind kb backfill <slack|resume|list|cancel>."""
  from __future__ import annotations
  import argparse
  import uuid
  from datetime import datetime, timezone


  def _iso_date(s: str) -> datetime:
      return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


  def build_parser() -> argparse.ArgumentParser:
      p = argparse.ArgumentParser(prog="breadmind kb backfill")
      sub = p.add_subparsers(dest="subcommand", required=True)

      slack = sub.add_parser("slack", help="Slack backfill")
      slack.add_argument("--org", required=True, type=uuid.UUID)
      slack.add_argument("--channel", required=True, action="append")
      slack.add_argument("--since", required=True, type=_iso_date)
      slack.add_argument("--until", required=True, type=_iso_date)
      slack.add_argument("--token-budget", type=int, default=500_000)
      slack.add_argument(
          "--include-threads", dest="include_threads",
          action="store_true", default=True)
      slack.add_argument(
          "--no-threads", dest="include_threads", action="store_false")
      slack.add_argument("--min-length", type=int, default=5)
      mode = slack.add_mutually_exclusive_group(required=True)
      mode.add_argument("--dry-run", action="store_true")
      mode.add_argument("--confirm", action="store_true")

      resume = sub.add_parser("resume", help="Resume a paused/failed job")
      resume.add_argument("job_id", type=uuid.UUID)

      lst = sub.add_parser("list", help="List recent backfill jobs")
      lst.add_argument("--org", required=True, type=uuid.UUID)
      lst.add_argument(
          "--status",
          choices=["running", "paused", "failed", "completed", "cancelled"])

      cancel = sub.add_parser("cancel", help="Cancel a running job")
      cancel.add_argument("job_id", type=uuid.UUID)

      return p


  def parse_slack_args(argv: list[str]) -> argparse.Namespace:
      return build_parser().parse_args(argv)
  ```

  `main.py` 수정 — `kb` subparser 추가, `kb backfill` 위임:

  ```python
  kb_parser = sub.add_parser("kb", help="Knowledge base operations")
  kb_sub = kb_parser.add_subparsers(dest="kb_command")
  bf_parser = kb_sub.add_parser("backfill", help="Bulk history backfill")
  bf_parser.add_argument("rest", nargs=argparse.REMAINDER)
  # ... in dispatch:
  if args.command == "kb" and args.kb_command == "backfill":
      from breadmind.kb.backfill.cli import build_parser as bf_build
      bf_args = bf_build().parse_args(args.rest)
      ...
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v`. 예상: 6 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/cli.py src/breadmind/main.py tests/kb/backfill/test_cli.py && git commit -m "feat(kb/backfill): CLI argparse for slack/resume/list/cancel subcommands"`

---

## Task 15: CLI dry-run 출력 골든 (spec §7 정확 매칭)

**Files:** Modify `src/breadmind/kb/backfill/cli.py`. Modify `tests/kb/backfill/test_cli.py`.

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  from breadmind.kb.backfill.cli import format_dry_run
  from breadmind.kb.backfill.base import JobReport, JobProgress
  import uuid
  from datetime import datetime, timezone


  def test_dry_run_output_matches_spec_section_7():
      report = JobReport(
          job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
          org_id=uuid.UUID("8c4f0000-0000-0000-0000-00000000009a"),
          source_kind="slack_msg",
          dry_run=True,
          estimated_count=3512,
          estimated_tokens=412_000,
          indexed_count=0,
          skipped={"signal_filter_short": 812, "signal_filter_bot": 640,
                   "signal_filter_no_engagement": 7103,
                   "signal_filter_mention_only": 414,
                   "acl_lock": 0, "archived": 0, "skipped_existing": 0},
          progress=JobProgress(discovered=12_481, filtered_out=8_969),
          sample_titles=[
              "[#engineering] postgres connection pool tuning recap",
              "[#engineering] re: deploy rollback procedure clarified",
          ],
      )
      ctx = {
          "project_name": "pilot-alpha",
          "team_id": "T012345",
          "team_name": "acme-eng",
          "channels": [("C0123456", "engineering"), ("C0987654", "ops")],
          "since": datetime(2026, 1, 1, tzinfo=timezone.utc),
          "until": datetime(2026, 4, 1, tzinfo=timezone.utc),
          "token_budget": 500_000,
          "monthly_remaining": 7_200_000,
          "monthly_ceiling": 10_000_000,
          "membership_count": 7,
          "membership_snapshotted_at": datetime(
              2026, 4, 26, 13, 42, 11, tzinfo=timezone.utc),
          "thread_root_count": 3_277,
          "top_level_count": 9_204,
      }
      out = format_dry_run(report, ctx)
      assert "Backfill DRY-RUN — Slack" in out
      assert "Org:" in out and "pilot-alpha" in out
      assert "Source:" in out and "slack_msg" in out
      assert "Instance:" in out and "T012345" in out and "acme-eng" in out
      assert "Channels:" in out and "#engineering (C0123456)" in out
      assert "Window:" in out and "2026-01-01T00:00:00Z" in out \
          and "half-open" in out
      assert "Token budget:" in out and "500,000" in out \
          and "7,200,000 / 10,000,000" in out
      assert "Membership lock:" in out and "7 members" in out
      assert "Discovery" in out
      assert "Discovered messages:" in out and "12,481" in out
      assert "top-level:" in out and "9,204" in out
      assert "thread roots:" in out and "3,277" in out
      assert "After signal filter:" in out and "3,512" in out \
          and "drop rate 71.9%" in out
      assert "signal_filter_short:" in out
      assert "Cost estimate" in out
      assert "Estimated tokens (body):" in out and "~412,000" in out \
          and "within budget: yes" in out
      assert "Sample titles" in out
      assert "No data was indexed." in out
      assert "To run for real: re-issue without --dry-run." in out
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_cli.py::test_dry_run_output_matches_spec_section_7 -v`. 예상: ImportError.

- [ ] **Step 3: 구현** — `cli.py`에 추가:

  ```python
  def format_dry_run(report, ctx: dict) -> str:
      def fmt_int(n: int) -> str:
          return f"{n:,}"
      since = ctx["since"].strftime("%Y-%m-%dT%H:%M:%SZ")
      until = ctx["until"].strftime("%Y-%m-%dT%H:%M:%SZ")
      drop = report.progress.discovered - report.estimated_count
      drop_pct = (drop / report.progress.discovered * 100
                  if report.progress.discovered else 0.0)
      within = "yes" if report.estimated_tokens <= ctx["token_budget"] \
          else "no"
      channels_line = ", ".join(
          f"#{name} ({cid})" for cid, name in ctx["channels"])
      lines = [
          "Backfill DRY-RUN — Slack",
          "========================",
          f"Org:             {report.org_id} (project: {ctx['project_name']})",
          f"Source:          {report.source_kind}",
          f"Instance:        {ctx['team_id']} (workspace {ctx['team_name']})",
          f"Channels:        {channels_line}",
          f"Window:          {since} → {until}  "
          "(filter: source_updated_at, half-open)",
          f"Token budget:    {fmt_int(ctx['token_budget'])}  (job)  /  "
          f"per-org monthly remaining: {fmt_int(ctx['monthly_remaining'])} "
          f"/ {fmt_int(ctx['monthly_ceiling'])}",
          f"Membership lock: {ctx['membership_count']} members snapshotted "
          f"at {ctx['membership_snapshotted_at'].strftime('%Y-%m-%dT%H:%M:%SZ')}"
          " (per-item ACL: label-only)",
          "",
          "Discovery",
          "---------",
          f"Discovered messages:        {fmt_int(report.progress.discovered)}",
          f"  - top-level:               {fmt_int(ctx['top_level_count'])}",
          f"  - thread roots:            {fmt_int(ctx['thread_root_count'])}",
          f"After signal filter:         {fmt_int(report.estimated_count)}"
          f"   (drop rate {drop_pct:.1f}%)",
          "Skipped (by reason)",
      ]
      for k in ("signal_filter_short", "signal_filter_bot",
               "signal_filter_no_engagement", "signal_filter_mention_only",
               "acl_lock", "archived", "skipped_existing"):
          v = report.skipped.get(k, 0)
          comment = "  (dry-run does not touch DB)" \
              if k == "skipped_existing" else ""
          lines.append(f"  - {k}: {fmt_int(v)}{comment}")
      lines += [
          "",
          "Cost estimate",
          "-------------",
          f"Estimated tokens (body):    ~{fmt_int(report.estimated_tokens)}"
          f"   (within budget: {within})",
          f"Estimated embeddings:        {fmt_int(report.estimated_count)}",
          f"Estimated DB rows:           {fmt_int(report.estimated_count)} "
          f"org_knowledge + {fmt_int(report.estimated_count)} kb_sources",
          "",
          f"Sample titles (10 of {fmt_int(report.estimated_count)})",
          "----------------------------",
      ]
      for t in report.sample_titles[:10]:
          lines.append(f"  {t}")
      lines += ["", "No data was indexed.",
                "To run for real: re-issue without --dry-run."]
      return "\n".join(lines)
  ```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v`. 예상: 7 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/cli.py tests/kb/backfill/test_cli.py && git commit -m "feat(kb/backfill): dry-run output formatter matching spec §7 golden"`

---

## Task 16: CLI confirm/실행 흐름 (real-run wiring + budget check)

**Files:** Modify `src/breadmind/kb/backfill/cli.py`. Modify `tests/kb/backfill/test_cli.py`.

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  async def test_run_command_dispatches_dry_run(monkeypatch, mem_backfill_db,
                                                 seeded_org, fake_redactor,
                                                 fake_embedder):
      from breadmind.kb.backfill import cli
      captured = {}
      async def fake_run(self, job):
          captured["dry_run"] = job.dry_run
          from breadmind.kb.backfill.base import JobReport
          return JobReport(
              job_id=uuid.uuid4(), org_id=job.org_id,
              source_kind=job.source_kind, dry_run=job.dry_run,
              estimated_count=0, estimated_tokens=0, indexed_count=0,
              progress=JobProgress(),
          )
      from breadmind.kb.backfill.runner import BackfillRunner
      monkeypatch.setattr(BackfillRunner, "run", fake_run)
      argv = ["slack", "--org", str(seeded_org), "--channel", "C1",
              "--since", "2026-01-01", "--until", "2026-04-01", "--dry-run"]
      rc = await cli.main_async(
          argv, db=mem_backfill_db, redactor=fake_redactor,
          embedder=fake_embedder, slack_session=_FakeSlack())
      assert rc == 0
      assert captured["dry_run"] is True


  async def test_real_run_aborts_when_monthly_budget_zero(
      monkeypatch, mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
  ):
      """If OrgMonthlyBudget.remaining() == 0, refuse to start."""
      from breadmind.kb.backfill import cli
      monkeypatch.setattr(
          "breadmind.kb.backfill.cli._monthly_remaining",
          lambda *_a, **_kw: 0)
      argv = ["slack", "--org", str(seeded_org), "--channel", "C1",
              "--since", "2026-01-01", "--until", "2026-04-01", "--confirm"]
      rc = await cli.main_async(
          argv, db=mem_backfill_db, redactor=fake_redactor,
          embedder=fake_embedder, slack_session=_FakeSlack())
      assert rc != 0
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v -k "dispatches_dry_run or budget_zero"`. 예상: AttributeError on `cli.main_async`.

- [ ] **Step 3: 구현** — `cli.py`에 추가:

  ```python
  async def main_async(
      argv: list[str], *, db, redactor, embedder, slack_session,
      vault=None, monthly_ceiling: int = 10_000_000,
  ) -> int:
      args = build_parser().parse_args(argv)
      if args.subcommand == "slack":
          return await _run_slack(
              args, db=db, redactor=redactor, embedder=embedder,
              slack_session=slack_session, vault=vault,
              monthly_ceiling=monthly_ceiling)
      if args.subcommand == "resume":
          return await _run_resume(
              args.job_id, db=db, redactor=redactor, embedder=embedder,
              slack_session=slack_session, vault=vault)
      if args.subcommand == "list":
          return await _run_list(args, db=db)
      if args.subcommand == "cancel":
          return await _run_cancel(args.job_id, db=db)
      return 2


  def _monthly_remaining(db, org_id, ceiling: int) -> int:
      from datetime import date
      from breadmind.kb.backfill.budget import OrgMonthlyBudget
      import asyncio
      b = OrgMonthlyBudget(db=db, ceiling=ceiling)
      today = date.today().replace(day=1)
      return asyncio.get_event_loop().run_until_complete(
          b.remaining(org_id, period=today))
  # NOTE: in async path use `await b.remaining(...)` directly; the sync
  # helper above exists only so monkeypatch in tests can stub a value.


  async def _run_slack(
      args, *, db, redactor, embedder, slack_session, vault, monthly_ceiling,
  ) -> int:
      from breadmind.kb.backfill.budget import OrgMonthlyBudget
      from breadmind.kb.backfill.runner import BackfillRunner
      from breadmind.kb.backfill.slack import SlackBackfillAdapter
      from datetime import date
      budget = OrgMonthlyBudget(db=db, ceiling=monthly_ceiling)
      remaining = await budget.remaining(args.org, period=date.today().replace(day=1))
      if args.confirm and remaining <= 0:
          print("Per-org monthly token ceiling exhausted; "
                "ask admin to lift before re-running.")
          return 3
      job = SlackBackfillAdapter(
          org_id=args.org,
          source_filter={"channels": args.channel,
                          "include_threads": args.include_threads},
          since=args.since, until=args.until,
          dry_run=args.dry_run, token_budget=args.token_budget,
          config={"min_length": args.min_length},
          vault=vault, credentials_ref=f"slack:org:{args.org}",
          session=slack_session)
      runner = BackfillRunner(
          db=db, redactor=redactor, embedder=embedder, org_budget=budget)
      report = await runner.run(job)
      if args.dry_run:
          ctx = await _build_dry_run_ctx(args, job, report, remaining,
                                         monthly_ceiling)
          print(format_dry_run(report, ctx))
      else:
          print(f"indexed={report.indexed_count} "
                f"errors={report.errors} cursor={report.cursor}")
      return 0
  ```

  `_run_resume`/`_run_list`/`_run_cancel`/`_build_dry_run_ctx` stubs도 같은 파일에 정의 (다음 task에서 강화).

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v`. 예상: 9 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/cli.py tests/kb/backfill/test_cli.py && git commit -m "feat(kb/backfill): CLI confirm/dry-run dispatcher with monthly budget pre-check"`

---

## Task 17: CLI resume/list/cancel + mid-flight archived handling

**Files:** Modify `src/breadmind/kb/backfill/cli.py`. Modify `tests/kb/backfill/test_cli.py`. Modify `runner.py` (mid-run archived → `skipped["archived"]`).

- [ ] **Step 1: 실패 테스트 추가** —

  ```python
  async def test_resume_loads_cursor_and_runs(monkeypatch, mem_backfill_db,
                                              seeded_org, fake_redactor,
                                              fake_embedder):
      from breadmind.kb.backfill.checkpoint import JobCheckpointer
      cp = JobCheckpointer(db=mem_backfill_db)
      job_id = await cp.start(
          org_id=seeded_org, source_kind="slack_msg",
          source_filter={"channels": ["C1"]}, instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10**9, created_by="t")
      await cp.checkpoint(job_id=job_id, cursor="1735689600000:C1:1.0",
                          progress={}, skipped={})
      await cp.finish(job_id=job_id, status="paused")
      from breadmind.kb.backfill import cli
      argv = ["resume", str(job_id)]
      rc = await cli.main_async(
          argv, db=mem_backfill_db, redactor=fake_redactor,
          embedder=fake_embedder, slack_session=_FakeSlack())
      assert rc == 0


  async def test_list_prints_recent_jobs(mem_backfill_db, seeded_org, capsys):
      from breadmind.kb.backfill import cli
      from breadmind.kb.backfill.checkpoint import JobCheckpointer
      cp = JobCheckpointer(db=mem_backfill_db)
      await cp.start(
          org_id=seeded_org, source_kind="slack_msg",
          source_filter={}, instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=1, created_by="t")
      argv = ["list", "--org", str(seeded_org)]
      rc = await cli.main_async(
          argv, db=mem_backfill_db, redactor=None,
          embedder=None, slack_session=None)
      assert rc == 0
      assert "running" in capsys.readouterr().out


  async def test_cancel_marks_job_cancelled(mem_backfill_db, seeded_org):
      from breadmind.kb.backfill import cli
      from breadmind.kb.backfill.checkpoint import JobCheckpointer
      cp = JobCheckpointer(db=mem_backfill_db)
      jid = await cp.start(
          org_id=seeded_org, source_kind="slack_msg",
          source_filter={}, instance_id="T1",
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=1, created_by="t")
      argv = ["cancel", str(jid)]
      rc = await cli.main_async(argv, db=mem_backfill_db, redactor=None,
                                embedder=None, slack_session=None)
      assert rc == 0
      row = await mem_backfill_db.fetchrow(
          "SELECT status FROM kb_backfill_jobs WHERE id=$1", jid)
      assert row["status"] == "cancelled"


  async def test_runner_marks_remaining_archived_midrun(
      mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
  ):
      """Mid-run archive: discover() raises ChannelArchived for channel C2;
      remaining items in C2 → skipped['archived'], C1 continues."""
      # see implementation for ChannelArchived class
      ...
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v -k "resume or list_prints or cancel_marks or archived_midrun"`. 예상: 4 fails.

- [ ] **Step 3: 구현** — cli.py에 `_run_resume`/`_run_list`/`_run_cancel` 채우기:

  ```python
  async def _run_list(args, *, db) -> int:
      sql = ("SELECT id, source_kind, status, started_at "
             "FROM kb_backfill_jobs WHERE org_id=$1")
      params = [args.org]
      if args.status:
          sql += " AND status=$2"
          params.append(args.status)
      sql += " ORDER BY created_at DESC LIMIT 50"
      for row in await db.fetch(sql, *params):
          print(f"{row['id']}  {row['source_kind']:<12}  "
                f"{row['status']:<10}  {row['started_at']}")
      return 0


  async def _run_cancel(job_id, *, db) -> int:
      await db.execute(
          "UPDATE kb_backfill_jobs SET status='cancelled', finished_at=now() "
          "WHERE id=$1 AND status IN ('running','paused')", job_id)
      return 0


  async def _run_resume(job_id, *, db, redactor, embedder, slack_session,
                        vault) -> int:
      row = await db.fetchrow(
          "SELECT * FROM kb_backfill_jobs WHERE id=$1", job_id)
      if row is None:
          print(f"job {job_id} not found")
          return 4
      if row["dry_run"]:
          print("dry-run resume is a no-op")
          return 0
      from breadmind.kb.backfill.runner import BackfillRunner
      from breadmind.kb.backfill.slack import SlackBackfillAdapter
      import json
      sf = json.loads(row["source_filter"]) if isinstance(
          row["source_filter"], str) else row["source_filter"]
      job = SlackBackfillAdapter(
          org_id=row["org_id"], source_filter=sf,
          since=row["since_ts"], until=row["until_ts"],
          dry_run=False, token_budget=row["token_budget"],
          vault=vault, credentials_ref=f"slack:org:{row['org_id']}",
          session=slack_session)
      job._resume_cursor = row["last_cursor"]  # adapter honours via discover()
      await BackfillRunner(db=db, redactor=redactor, embedder=embedder).run(job)
      return 0
  ```

  Slack adapter discover() — `_resume_cursor` 가 있으면 첫 채널의 `oldest = self._cursor_to_oldest(self._resume_cursor)` 사용.

  Runner — `ChannelArchived` (slack.py에 정의) 캐치 시 `skipped["archived"] += 1` 카운트, 다음 채널 계속.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/kb/backfill/test_cli.py -v`. 예상: 13 pass.

- [ ] **Step 5: Commit** — `git add src/breadmind/kb/backfill/cli.py src/breadmind/kb/backfill/slack.py src/breadmind/kb/backfill/runner.py tests/kb/backfill/test_cli.py && git commit -m "feat(kb/backfill): resume/list/cancel CLI + mid-run archived handling"`

---

## Task 18: e2e — 가짜 Slack 클라이언트 + testcontainers Postgres 통합

**Files:** Create `tests/integration/kb/backfill/__init__.py`, `tests/integration/kb/backfill/test_e2e_slack.py`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/integration/kb/backfill/test_e2e_slack.py`:

  ```python
  from __future__ import annotations
  import uuid
  from datetime import datetime, timezone
  import pytest
  from breadmind.kb.backfill.runner import BackfillRunner
  from breadmind.kb.backfill.slack import SlackBackfillAdapter
  from breadmind.kb.backfill.budget import OrgMonthlyBudget

  pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


  async def test_e2e_200_messages_two_channels_indexes_post_filter(
      testcontainers_pg_with_010, seeded_org, real_redactor, real_embedder,
      fake_slack_with_200_messages,
  ):
      job = SlackBackfillAdapter(
          org_id=seeded_org,
          source_filter={"channels": ["C1", "C2"], "include_threads": True},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10**9,
          vault=_FixtureVault(), credentials_ref="slack:e2e",
          session=fake_slack_with_200_messages)
      runner = BackfillRunner(
          db=testcontainers_pg_with_010, redactor=real_redactor,
          embedder=real_embedder,
          org_budget=OrgMonthlyBudget(
              db=testcontainers_pg_with_010, ceiling=10**9))
      report = await runner.run(job)
      # Fixture has ~30% signal pass rate.
      assert 50 <= report.indexed_count <= 80
      rows = await testcontainers_pg_with_010.fetch(
          "SELECT COUNT(*) AS c FROM org_knowledge "
          "WHERE project_id=$1 AND source_kind='slack_msg'", seeded_org)
      assert rows[0]["c"] == report.indexed_count


  async def test_e2e_resume_after_kill_no_duplicates(
      testcontainers_pg_with_010, seeded_org, real_redactor,
      flaky_embedder_at_73, fake_slack_with_200_messages,
  ):
      """flaky_embedder_at_73 raises on item 73; subsequent resume completes."""
      job = SlackBackfillAdapter(
          org_id=seeded_org, source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10**9,
          vault=_FixtureVault(), credentials_ref="slack:e2e",
          session=fake_slack_with_200_messages)
      runner = BackfillRunner(
          db=testcontainers_pg_with_010, redactor=real_redactor,
          embedder=flaky_embedder_at_73)
      try:
          await runner.run(job)
      except Exception:
          pass
      job2 = SlackBackfillAdapter(
          org_id=seeded_org, source_filter={"channels": ["C1"]},
          since=datetime(2026, 1, 1, tzinfo=timezone.utc),
          until=datetime(2026, 4, 1, tzinfo=timezone.utc),
          dry_run=False, token_budget=10**9,
          vault=_FixtureVault(), credentials_ref="slack:e2e",
          session=fake_slack_with_200_messages)
      job2._resume_cursor = await _last_cursor(testcontainers_pg_with_010)
      runner2 = BackfillRunner(
          db=testcontainers_pg_with_010, redactor=real_redactor,
          embedder=_RecoveredEmbedder())
      report = await runner2.run(job2)
      rows = await testcontainers_pg_with_010.fetch(
          "SELECT source_native_id, COUNT(*) c FROM org_knowledge "
          "WHERE project_id=$1 GROUP BY source_native_id HAVING COUNT(*)>1",
          seeded_org)
      assert rows == []  # uq_org_knowledge_source_native dedupes
  ```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/integration/kb/backfill/test_e2e_slack.py -v -m e2e`. 예상: fixtures 미정의로 fail.

- [ ] **Step 3: 구현** — fixtures 와 fake Slack client (200 메시지 시드: 70 short + 50 bot + 30 zero-eng + 50 signal + 20 mention-only across 2 channels). `_FixtureVault`/`_RecoveredEmbedder`/`_last_cursor` helpers. `real_redactor = Redactor.default()`, `real_embedder = EmbeddingService(provider="fastembed")`.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/integration/kb/backfill/test_e2e_slack.py -v -m e2e`. 예상: 2 pass.

- [ ] **Step 5: Commit** — `git add tests/integration/kb/backfill/ && git commit -m "test(kb/backfill): e2e Slack adapter + Postgres 010 integration with resume dedup"`

---

## Self-Review

### Spec coverage 매핑

| Spec 섹션 | Task |
|---|---|
| §1 Overview & Goals (5단계 lifecycle, guardrails) | T7+T8+T9 (runner) |
| §1 Guardrails: explicit channel+window | T14 (CLI required args), T10 (PermissionError on missing) |
| §1 Guardrails: PII redact strengthened | T8 (abort_if_secrets+redact 순서) |
| §1 Guardrails: signal filter | T12 |
| §1 Guardrails: token budget cap + progress | T8 (budget gate), T3 (JobProgress) |
| §1 Guardrails: dry-run preview | T7+T15 |
| §1 Guardrails: dual timestamps | T2 (BackfillItem), T1 (DDL) |
| §1 Guardrails: parent_ref 1st-class | T2, T1 |
| §1 Guardrails: ACL snapshot at prepare | T10 |
| §1 Guardrails: per-org monthly ceiling | T1 (DDL), T6 (tracker), T16 (CLI pre-check) |
| §3 BackfillJob ABC (cursor_of/instance_id_of/Skipped) | T4 |
| §3 D1-D5 invariants (range/cursor/skipped/ACL/instance) | T11(D1), T13(D2), T12(D3), T12(D4), T5(D5) |
| §4 Data flow + 50/30s checkpoint + token estimate | T7+T8+T9 |
| §4 Author pseudonymisation (P3) | T8 (`_pseudonymise_author`) |
| §5 DB schema (org_knowledge cols, jobs, budget) | T1 |
| §6.1 source_filter schema | T10 (validate channels), T14 (CLI) |
| §6.2 API usage (history+replies+info+members) | T10+T11 |
| §6.3 rate limit + retry + token vault | T11 (`_call_with_retry`), T10 (vault stub) |
| §6.3a ACL prepare/filter labelling | T10+T12 |
| §6.4 4 signal heuristics + tunable | T12 |
| §6.5 source_native_id rule | T11 |
| §6.6 cursor_of format | T13 |
| §6.7 range filter D4 | T11 (oldest/latest + reply client cut) |
| §7 dry-run output | T15 |
| §8 CLI subcommands (slack/resume/list/cancel) | T14+T16+T17 |
| §8 programmatic API | T7-T9 (runner.run interface) |
| §9 errors: 10% threshold, pause/resume, P4 fail-closed, BudgetExceeded→paused, OrgMonthlyBudgetExceeded→paused, token_budget→completed | T8(10%), T9+T17(resume), T10(P4), T9(paused), T8(budget_hit) |
| §10 test strategy: unit/integration/CLI golden | T2-T17 (unit), T18 (integration) |
| §11 P1/P3/P4 binding | T1+T6+T16 (P1), T8 (P3), T10+T17 (P4) |
| §12 cross-adapter invariants 1-12 | 모두 contract 코드 (T2-T4) 와 spec 주석으로 표현 |

### 인라인 fix 한 사항
- 초안에서 `cursor_for` 로 적은 메서드를 spec 의 `cursor_of` 로 통일 (T4/T13).
- `JobReport.skipped` 를 `int` 로 잠시 표기했다가 spec §11 §12-12 따라 `dict[str, int]` 로 통일 (T3).
- `instance_id_of` 시그니처를 `(source_filter)` 인자 받는 형태로 spec §3 일치시킴 (T4/T10).
- T8 의 `_maybe_abort` 임계값 200 items / 10% 를 `error_ratio_min_items=200`/`error_ratio_threshold=0.10` 으로 명시 (spec §9).
- T11 의 thread roll-up 4000 chars 를 spec §6.4 `_CHUNK_CHAR_BUDGET` 와 동일 상수로 매칭.
- T17 의 archived mid-run 시 `skipped["archived"] += 1` (P4 mid-run path) 명시.
- BreadMind 가 click 이 아닌 argparse 를 쓴다는 사실을 반영해 CLI 구현 전체 argparse 로 변환 (spec 명시는 click 이 아니라 "CLI" 였음).

---

**Tasks:** 18.
**예상 구현 소요:** 18 tasks × 평균 4-5분/step × 5 steps ≈ 6-7 시간 active TDD (체크포인트 후 머지 검토 포함 시 2 PR로 분할 권장: T1-T9 (파이프라인 코어) + T10-T18 (Slack + CLI + e2e)).
