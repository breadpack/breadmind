# Confluence Backfill Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Prerequisite:** Sub-project 1 master 머지 완료. `BackfillJob`, `BackfillItem`, `JobReport`, `JobProgress`, `BackfillRunner`, `HourlyPageBudget` (instance-keyed), `kb_backfill_jobs` 테이블, `kb_backfill_org_budget` 테이블, `org_knowledge` 컬럼 추가 (`source_kind`, `source_native_id`, `source_created_at`, `source_updated_at`, `parent_ref`) 가 master 에 들어와 있어야 본 plan 시작.

**Goal:** 기존 `ConfluenceConnector` (incremental) 를 건드리지 않고 `ConfluenceBackfillAdapter` 신규 클래스를 `src/breadmind/kb/backfill/adapters/confluence.py` 에 추가하여 공통 `BackfillJob` 파이프라인이 Confluence 공간/서브트리/page-id 묶음을 양방향 시간창으로 일괄 적재하게 한다.

**Architecture:** `ConfluenceBackfillAdapter` 가 `BackfillJob` 의 ABC 를 구현하는 신규 클래스로, 기존 `ConfluenceConnector` 와 하나의 모듈도 공유하지 않는다 (C2). 시간창은 Confluence CQL `lastModified >= "since" AND lastModified < "until"` 으로 server-side 필터 (D4); 기존 connector 의 `_get_with_retry` / `_PAGE_LIMIT` / `html_to_markdown` / `_chunk_markdown` 등 재사용 함수는 connector 모듈에서 직접 import 하여 코드 중복 없이 사용한다. 권한 락은 `prepare()` 직전 활성 멤버 셋 1회 스냅샷 + per-item `restrictions.read` expand 로 N+1 회피 (C1).

**Tech Stack:** Python 3.12+, aiohttp/httpx, pytest-asyncio.

---

## File Structure

- `src/breadmind/kb/backfill/adapters/__init__.py` (신규) — `ConfluenceBackfillAdapter` re-export.
- `src/breadmind/kb/backfill/adapters/confluence.py` (신규) — `ConfluenceBackfillAdapter(BackfillJob)` 신규 클래스 본체.
- `src/breadmind/kb/connectors/confluence.py` (수정 최소) — 모듈 docstring 에 "incremental 전용; backfill 은 `kb/backfill/adapters/confluence.py`" 명시 + 재사용 함수 (`html_to_markdown`, `_chunk_markdown`, `_PAGE_LIMIT`, `_BACKOFF_SECONDS`) 가 외부 import 가능하도록 노출 (이미 module-level 또는 `ConfluenceConnector` classvar 로 접근 가능 — 코드 변경 없이 import 만 추가).
- `src/breadmind/kb/backfill/cli.py` (수정 — 또는 dispatcher 가 plug-in 방식이면 신규 어댑터 등록만) — `breadmind kb backfill confluence` 서브명령을 dispatcher 에 등록.
- `tests/kb/backfill/adapters/test_confluence.py` (신규) — backfill adapter 단위/시그널 테스트. cassette 는 `tests/kb/backfill/adapters/cassettes/confluence_backfill_*.yaml` 에 분리.
- `tests/kb/backfill/adapters/test_confluence_cli.py` (신규) — CLI 골든 출력 + dry-run 스냅샷.
- `tests/kb/connectors/test_confluence.py` (수정 0) — 기존 incremental 테스트 회귀 가드. **본 plan 의 모든 task 가 이 파일을 변경해서는 안 된다.**

---

## Tasks

### Phase 0 — Regression Guard 먼저

- [ ] **Task 0** — Regression baseline: 기존 `tests/kb/connectors/test_confluence.py` 전체를 현재 master 에서 실행하고 모두 green 임을 확인. 베이스라인 출력을 PR 설명에 보존. 본 plan 의 *모든 후속 task 의 commit 전*에 이 테스트가 다시 green 임을 검증한다 (C2 위반 가드, Risk §12).

### Phase 1 — Adapter Skeleton

- [ ] **Task 1** — `ConfluenceBackfillAdapter` 클래스 골격 (TDD: 첫 테스트는 `test_subclass_has_required_class_attrs`).
  - `source_kind: ClassVar[str] = "confluence_page"`.
  - `__init__` 시그니처는 `BackfillJob` 와 동일 (`org_id`, `source_filter`, `since`, `until`, `dry_run`, `token_budget`, `config`) + 어댑터 전용: `base_url`, `credentials_ref`, `vault`, `db`, `http_session=None`, `budget=None`.
  - 추상 메서드 `prepare/discover/filter/instance_id_of` 만 빈 구현 (`NotImplementedError`).
  - 회귀 가드: Task 0 재실행.

- [ ] **Task 2** — `instance_id_of(source_filter) -> str` 구현 (D5).
  - Cloud: `https://<tenant>.atlassian.net/wiki` / on-prem: 호스트 URL.
  - 본 어댑터는 `self._base_url` 을 sha256 16 hex 로 해시하여 반환 (spec §5.1).
  - 테스트: `test_instance_id_distinct_for_cloud_vs_onprem` — 같은 org 가 cloud + on-prem 에 동시 backfill 시 두 instance_id 가 다름.
  - 회귀 가드.

### Phase 2 — Discover (CQL + Pagination)

- [ ] **Task 3** — CQL query 빌더 (`_build_cql(source_filter, since, until) -> str`) — pure function.
  - `kind=space` → `space in ("ENG","OPS") AND type=page AND status=current AND lastModified >= "<since_iso>" AND lastModified < "<until_iso>"` + optional `AND label NOT IN ("draft","wip")` (`labels_exclude`).
  - `kind=subtree` → `ancestor = "<root>" AND type=page AND status=current AND lastModified >= ... AND lastModified < ...`.
  - `kind=page_ids` → CQL 사용 안 함 (id 별 직접 fetch — Task 5 에서).
  - 테스트: `test_cql_query_built_for_space_filter` (D4 server-side 윈도우 검증), `test_cql_query_for_subtree`, `test_cql_query_excludes_labels`.
  - 회귀 가드.

- [ ] **Task 4** — `discover()` 페이지네이션 — `_PAGE_LIMIT = 50` 재사용.
  - `GET /rest/api/content/search?cql=...&expand=body.storage,version,history,metadata.labels,restrictions.read,ancestors&limit=50` 호출.
  - 기존 connector 의 `_get_with_retry` 를 import 또는 인라인 재구현 (단일 helper 모듈로 빼지 말 것 — 기존 connector 영향 zero 원칙).
  - `_links.next` 따라 다음 페이지로 이동, 빈 응답 시 종료.
  - 응답 page → `BackfillItem` 매핑 (Task 6 에서 본격).
  - 테스트: `test_discover_paginates_via_links_next`, `test_discover_429_retry_with_retry_after` (기존 cassette 패턴 답습).
  - 회귀 가드.

- [ ] **Task 5** — `kind=page_ids` 분기 — id 별 직접 fetch.
  - 각 id 별 `GET /rest/api/content/{id}?expand=body.storage,version,history,metadata.labels,restrictions.read,ancestors`.
  - `since/until` 윈도우는 client-side 컷 (`source_updated_at` 가 `[since, until)` 안일 때만 yield) — D4 spec 합의 ("server-side 가 안 되면 client-side").
  - 테스트: `test_page_ids_filter_yields_only_window`.
  - 회귀 가드.

### Phase 3 — BackfillItem Mapping (D3 + D6)

- [ ] **Task 6** — page payload → `BackfillItem` 매핑.
  - `source_kind = "confluence_page"`, `source_native_id = page.id`.
  - `source_uri = f"{base_url}{page._links.webui}"` (resolved).
  - `title = page.title`, `body = html_to_markdown(page.body.storage.value)` — 기존 함수 재사용.
  - `source_created_at = page.history.createdDate` (D6).
  - `source_updated_at = page.version.when` (D6).
  - `author = (page.history.createdBy or {}).get("accountId")` (Cloud) — null safe.
  - `parent_ref = f"confluence_page:{page.ancestors[-1].id}"` if ancestors 비어있지 않을 때 (D3, spec §3).
  - `extra = {"space_key": ..., "labels": [...], "restrictions": {...}, "raw": page}` — adapter-private.
  - 테스트: `test_backfill_item_carries_parent_ref_and_timestamps` (D3 + D6 모두), `test_body_uses_storage_format_not_view` (Q-CF-3 결정 검증).
  - 회귀 가드.

### Phase 4 — ACL Snapshot & Filter (C1)

- [ ] **Task 7** — `prepare()` — 활성 멤버 셋 스냅샷 (C1).
  - `self._membership_snapshot: frozenset[str]` 결정 (org_projects member 테이블 기반; Q-CF-5 미해결분은 spec 따라 plug-in 으로 두고 본 plan 은 "현재 시점 멤버 셋 resolver" 시그니처만 받는다 — `member_resolver: Callable[[uuid.UUID], Awaitable[frozenset[str]]]` 를 `__init__` 에 주입).
  - 같은 시점에 `instance_id` 도 결정해서 `self._instance_id` 캐시 (Task 2 재호출 방지).
  - `prepare()` 는 한 번만 호출됨 — 재호출 시 noop (`if self._membership_snapshot is not None: return`).
  - 테스트: `test_active_members_snapshot_taken_at_discover_start`, `test_prepare_is_idempotent`.
  - 회귀 가드.

- [ ] **Task 8** — `filter(item) -> bool` 시그널 + ACL 표시 (D1 키 정확히 일치).
  - `filter()` 는 sync + cheap (spec §3 합의 — N+1 ban).
  - 다음 순서로 검사:
    1. `archived` (`extra["space_status"] == "archived"` 또는 `extra["page_metadata"]["archived"] is True`) → False, `extra["_skip_reason"] = "archived"`.
    2. `draft` (`extra["status"] != "current"`) → False, `"draft"`. (CQL 으로도 server-side 가드되지만 client-side 도 한 번 더 — 방어층.)
    3. `attachment_only` (body 비고 `extra["has_attachments"]` 만 있음) → False, `"attachment_only"`.
    4. `empty_page` (`len(item.body.strip()) < 50`) → False, `"empty_page"`.
    5. ACL: `restrictions.read.users + restrictions.read.groups` 가 비어있지 않을 때:
       - 페이지 허용 셋 `P` 와 `M = self._membership_snapshot` 의 교집합이 비어있으면 → False, `"acl_lock"` (drop, D1 키 일치).
       - 비어있지 않으면 → True, `extra["_acl_mark"] = "RESTRICTED"` + `extra["_source_channel"] = f"confluence:{space}:restricted"` (visibility tag, §5).
    6. 그 외 → True, `extra["_acl_mark"] = "PUBLIC"`, `extra["_source_channel"] = f"confluence:{space}"`.
  - 테스트: `test_archived_space_skipped`, `test_draft_pages_skipped`, `test_attachment_only_skipped`, `test_empty_page_skipped`, `test_acl_lock_drop_when_no_active_member`, `test_restricted_keep_when_member_intersects`.
  - 회귀 가드.

### Phase 5 — Cursor / Resume (D2)

- [ ] **Task 9** — `cursor_of(item) -> str` 오버라이드.
  - 형식: `f"{int(item.source_updated_at.timestamp() * 1000)}:{item.source_native_id}"` — D2 spec 합의 (last_modified:content_id 인코딩).
  - Monotonic in `source_updated_at`; tie-break by `id`.
  - 테스트: `test_cursor_of_format_matches_spec`.
  - 회귀 가드.

- [ ] **Task 10** — `--resume <cursor>` 처리 — `discover()` 가 resume 토큰을 받으면 CQL 에 `lastModified > "<iso>" OR (lastModified = "<iso>" AND id > "<page_id>")` 추가.
  - resume 인자는 `__init__` 또는 `prepare(resume_cursor=...)` 로 주입.
  - 테스트: `test_resume_from_cursor_skips_already_done`, `test_token_budget_terminates_gracefully` (partial JobReport 의 cursor 가 채워지는지 확인).
  - 회귀 가드.

### Phase 6 — Dedup & SourceMeta

- [ ] **Task 11** — `already_ingested` 멱등성 (spec §6.3).
  - `discover()` 직후 단일 IN-list 조회 (`SELECT source_native_id FROM org_knowledge WHERE project_id=$1 AND source_kind='confluence_page' AND source_native_id = ANY($2)`) 로 prefetch — Risk 12 의 N+1 회피.
  - 이미 적재된 `source_native_id` 는 `extra["_skip_reason"] = "already_ingested"` (Sub-project 1 runner 가 `skipped_existing` 키로 처리 — adapter 는 "already_ingested" 키를 별도로 쓰지 말고 runner 의 reserved key 를 사용해야 함. **self-review fix**: spec §6.3 에서 `"already_ingested"` 라고 적었지만 Sub-project 1 spec §3 에서 reserved key 는 `"skipped_existing"` — runner 가 이를 처리하므로 어댑터는 `_skip_reason = "skipped_existing"` 를 사용한다).
  - `--reingest` 플래그가 True 면 dedup skip 건너뛰고 모두 yield.
  - 테스트: `test_already_ingested_skipped`, `test_reingest_flag_overrides_dedup`.
  - 회귀 가드.

- [ ] **Task 12** — `extracted_from = "confluence_backfill"` 라벨 (incremental 의 `"confluence_sync"` 와 구분).
  - `BackfillItem.extra["_extracted_from"] = "confluence_backfill"` 또는 어댑터가 store 단계에서 SourceMeta 를 만든다면 거기에. (Sub-project 1 runner 가 SourceMeta 를 어떻게 채우는지에 따라 — `extra` 키 하나로 합의.)
  - 테스트: `test_source_meta_extracted_from_backfill`.
  - 회귀 가드.

### Phase 7 — CLI

- [ ] **Task 13** — CLI 서브명령 `breadmind kb backfill confluence` 등록.
  - 플래그: `--org <uuid|slug>` (org_id Phase 2 v2 resolver 재사용), `--space ENG` (반복), `--page-ids 12,34`, `--subtree <root_id>` (셋 중 하나만), `--since YYYY-MM-DD` / `--until YYYY-MM-DD` (UTC 자정 정규화), `--token-budget`, `--dry-run`, `--reingest`, `--resume <cursor>`, `--labels-exclude draft,wip`.
  - `--space` ↔ `--page-ids` ↔ `--subtree` 상호 배타 — Click `cls=MutuallyExclusiveGroup` 또는 명시 검증.
  - source_filter 변환: `--space` → `{kind:"space", spaces:[...], labels_exclude:[...]}`, `--page-ids` → `{kind:"page_ids", ids:[...]}`, `--subtree` → `{kind:"subtree", root_page_id:"..."}`.
  - 테스트: `test_cli_space_flag_builds_source_filter`, `test_cli_mutually_exclusive_scope_flags`, `test_cli_resolves_org_slug_to_uuid`.
  - 회귀 가드.

- [ ] **Task 14** — Dry-run 출력 포맷 (spec §8 과 정확히 일치하는 섹션 순서).
  - 섹션: `BackfillJob[confluence] org=...`, `source_filter`, `budget`, `Discover`, `Filter`, `Redact`, `Embed (estimated)`, `Store (DRY-RUN)`, `Token budget`, `Sample skips`.
  - skip 사유 키 순서는 알파벳 정렬 (`archived, draft, empty_page, attachment_only, acl_lock, restricted, skipped_existing`).
  - **self-review fix**: spec §8 의 `already_ingested` 키는 Task 11 결정에 따라 `skipped_existing` 으로 출력 (runner reserved key 와 일관).
  - Sample skips: 각 reason 별 처음 N=1 개 (page id + title) — Sub-project 1 합의 (가독성).
  - 테스트: `test_dry_run_output_matches_spec_layout` (golden snapshot), `test_dry_run_does_not_call_review_queue` (DB write 0 검증).
  - 회귀 가드.

### Phase 8 — Budget / Termination

- [ ] **Task 15** — `HourlyPageBudget` 가 `(org_id, instance_id)` 로 keyed 동작 검증.
  - 어댑터는 budget 객체에 `(org_id, instance_id)` 만 전달; budget 자체 구현은 Sub-project 1 책임.
  - 테스트: `test_hourly_budget_keyed_by_instance` (D5: cloud + on-prem 동시 backfill 시 instance 별 독립 budget).
  - 회귀 가드.

- [ ] **Task 16** — `org_monthly_ceiling` graceful pause.
  - `OrgMonthlyBudgetExceeded` 가 raise 되면 `JobReport.terminated_by = "org_monthly_ceiling"` + cursor 채움 — 어댑터는 백본의 강제를 그대로 따른다 (spec §6.4).
  - 테스트: `test_org_monthly_ceiling_terminates_run` (Sub-project 1 의 OrgMonthlyBudget stub 사용).
  - 회귀 가드.

### Phase 9 — JobReport Shape & E2E

- [ ] **Task 17** — `JobReport` 스키마 일치성.
  - `skipped: dict[str, int]` (D1) — Confluence 키 셋 = `{empty_page, archived, restricted, draft, attachment_only, acl_lock, skipped_existing, redact_dropped}`.
  - `cursor: str | None` (D2) — Task 9 형식.
  - 테스트: `test_job_report_shape_matches_backbone` (D1 + D2 둘 다).
  - 회귀 가드.

- [ ] **Task 18** — 회귀 가드 테스트 (C2 — incremental 흐름 무영향).
  - `test_incremental_path_unaffected` — 기존 `ConfluenceConnector._do_sync` 가 본 plan 적용 후에도 cursor / processed / errors 동작 동일함을 명시적으로 다시 검증.
  - 본 테스트는 `tests/kb/connectors/test_confluence.py` 가 아니라 `tests/kb/backfill/adapters/test_confluence.py` 에 추가 (incremental 테스트 파일을 본 plan 이 변경하지 않는다는 원칙).
  - 회귀 가드.

- [ ] **Task 19** — E2E 적분 테스트 (`tests/integration/kb/backfill/test_confluence_e2e.py`, marked `slow`).
  - Testcontainers Postgres + migration 010 (Sub-project 1) 적용된 상태에서, 200 페이지 across 2 spaces 가 들어있는 fake Confluence client 로 end-to-end 실행.
  - Assert: `org_knowledge` 행 수, `kb_sources` 행 수, `kb_backfill_jobs.status='completed'`, `progress_json` ↔ `JobReport` 일관성, `extracted_from='confluence_backfill'`, `parent_ref` 가 subtree 시나리오에서 채워짐, dedup index 가 재실행 시 추가 행 없음.

---

## Spec Coverage Mapping

| Spec 섹션 | 본 plan task |
|---|---|
| §1 Overview / 1.2 Backfill 의의 | Phase 0~1 (별도 클래스로 분리, C2) |
| §2 Gap 분석 / §2.1 CQL 사용 | Task 3, 4, 9 |
| §3 데이터 매핑 / §3.1 storage vs view | Task 6 (test_body_uses_storage_format_not_view) |
| §4 시그널 필터 (empty/archived/draft/attachment_only/comment/size) | Task 8 |
| §5 권한 락 (C1) / §5.1 instance budget (D5) | Task 7, 8 (acl_lock), Task 15 |
| §6.1 source_filter 형태 | Task 3, 5, 13 |
| §6.2 단계 매핑 (BackfillJob lifecycle) | Phase 1~9 전체 |
| §6.3 dedup 멱등성 | Task 11 |
| §6.4 종료 조건 (token_budget / org_monthly / hourly_budget / cancelled) | Task 10, 15, 16 |
| §7 CLI 엔트리포인트 | Task 13, 14 |
| §8 Dry-run 출력 | Task 14 |
| §9 테스트 전략 (모든 테스트 케이스) | Phase 1~9 의 각 task 테스트 |
| §10.1 해결 (C2/D6) / §10.2 남은 OQ | C2 = Task 0/18, D6 = Task 6, Q-CF-5 = Task 7 (resolver 주입), Q-CF-3 = Task 6 |
| §11 Non-Goals (`_do_sync` 시그니처/cursor 의미 변경 금지, attachment skip, 과거 ACL 미재현) | Task 0, 7, 8, 18 |
| §12 Risks (CQL 권한 / restrictions expand 부하 / dedup N+1 / created_at 가중치 왜곡 / **C2 위반**) | Task 7 (스냅샷 1회), Task 11 (IN-list prefetch), Task 18 (회귀 가드), Task 6 (D6 보존), Task 13 (smoke 1-page dry-run — `--dry-run` flow) |
| §13 Out-of-spec (E2E facade 미터치) | Task 19 (별도 facade) |

---

## No Placeholders / Self-Review Inline Fixes

1. **already_ingested → skipped_existing 키 정렬** — spec §6.3 / §8 은 `already_ingested` 라는 키를 쓰지만 Sub-project 1 spec §3 / §11 에서 runner reserved key 는 `"skipped_existing"`. 본 plan 은 Task 11 / Task 14 에서 명시적으로 `skipped_existing` 으로 통일.
2. **CLI `--since/--until` 의미 = `source_updated_at`** (Q-CF-7 결정 D6 반영) — Task 13 에 명시.
3. **`prepare()` 한 번 호출 보장** — Task 7 idempotent 가드.
4. **regression guard 가 모든 task 의 commit 전에 실행** — Phase 0 의 Task 0 + 각 task 의 "회귀 가드" 항목으로 강제. C2 위반 시 어떤 task 도 commit 되어선 안 됨.
5. **`<Source>BackfillAdapter` 명명 일관성** — `ConfluenceBackfillAdapter` 로 통일 (Sub-project 1 §6 명명 규칙). 별칭 / legacy 이름 도입 안 함.
6. **기존 incremental 테스트 파일 미터치** — Task 18 의 회귀 가드 테스트도 backfill 테스트 디렉터리에 추가하여 incremental 테스트 파일 boundary 불변.
7. **재사용 함수 import 만, helper 모듈 추출 금지** — `html_to_markdown` 은 `confluence.py` 의 module-level 함수라 그대로 import 가능. `_chunk_markdown` 은 `ConfluenceConnector._chunk_markdown` (staticmethod) — staticmethod 그대로 호출 (`ConfluenceConnector._chunk_markdown(...)`). `_get_with_retry` 는 instance method 라 어댑터 자체 helper 로 인라인 재구현 (모듈 분리 시 incremental 영향 위험; 코드 중복 감수).
8. **Q-CF-2 (visibility 정식 컬럼)** 미해결 — `extra["_source_channel"]` 우회 (Task 8) 로 임시 처리 + 본 plan 범위 외 (별도 마이그레이션 spec).

---

## Reused Functions from `src/breadmind/kb/connectors/confluence.py`

| 재사용 대상 | 재사용 방식 | 사용 task |
|---|---|---|
| `html_to_markdown(html)` (module-level) | `from breadmind.kb.connectors.confluence import html_to_markdown` | Task 6 |
| `ConfluenceConnector._chunk_markdown` (staticmethod) | `ConfluenceConnector._chunk_markdown(text, budget)` 직접 호출 | Task 6 (필요 시 Sub-project 1 runner 가 chunking 담당이면 어댑터에서는 미사용) |
| `ConfluenceConnector._CHUNK_CHAR_BUDGET = 4000` (ClassVar) | 동일 상수 import | Task 6 |
| `ConfluenceConnector._PAGE_LIMIT = 50` (ClassVar) | 동일 상수 import | Task 4 |
| `ConfluenceConnector._BACKOFF_SECONDS = (60, 300, 1800)` (ClassVar) | 동일 상수 import; backoff 로직 자체는 어댑터 인라인 재구현 | Task 4 |
| `ConfluencePage` dataclass | 어댑터는 자체 raw payload 처리; **재사용 안 함** (incremental 결합 회피) | — |
| `_build_auth_header` (instance method) | 동일 로직 (vault → `email:api_token` → base64 → `Basic ...`) 을 어댑터 helper 로 인라인 재구현; 중복은 의도적 (incremental 결합 회피) | Task 4 |
| `refresh_size_metric()` | backfill 종료 후 호출 — `from breadmind.kb.connectors.confluence import ConfluenceConnector` 후 `await ConfluenceConnector.build_for_tests(...)` 가 아니라, **module-level helper 로 추출하지 않고** Sub-project 1 runner 가 store 직후 호출하는 책임으로 위임 (어댑터는 직접 안 부름). | — (runner 책임) |
| `HourlyPageBudget` | `from breadmind.kb.connectors.rate_limit import HourlyPageBudget` (이미 공용 모듈) | Task 15 |
| `BudgetExceeded` | 동일 import | Task 15 |
| `SourceMeta` | `from breadmind.kb.types import SourceMeta` — store 단계는 runner 책임이지만 어댑터가 SourceMeta 를 채워 `extra` 로 넘기는 패턴이면 import | Task 12 |

---

## Definition of Done

- 모든 task 의 테스트 green + Task 0 의 incremental regression suite green.
- `ConfluenceConnector` 의 `_do_sync` / `_scan_retirements` / `_E2EConfluenceFacade` / `build_for_e2e` / `build_for_tests` 가 본 plan 적용 전후 byte-identical (의도적 import 노출 docstring 추가는 예외).
- `breadmind kb backfill confluence --space ENG --since 2025-01-01 --dry-run` 이 spec §8 과 같은 섹션으로 출력.
- `JobReport.skipped` 키 = `{empty_page, archived, restricted, draft, attachment_only, acl_lock, skipped_existing, redact_dropped}` (D1).
- `JobReport.cursor` 형식 = `"<ms>:<page_id>"` (D2).
- E2E 테스트 (Task 19) 가 200 페이지 fake fixture 로 통과, dedup 재실행 시 행 추가 없음.
