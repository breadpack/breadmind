# Notion Backfill Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Prerequisite:** Sub-project 1 (`backfill-pipeline-slack`) plan이 완료되어 `BackfillJob` / `BackfillItem` / `JobReport` / `JobProgress` / `BackfillRunner` / `OrgMonthlyBudget` / `HourlyPageBudget` (instance-keyed) 가 master에 머지된 상태여야 본 plan의 Task 1 시작 가능. 본 plan 내내 백본 컴포넌트 시그니처는 spec §3 (Sub-project 1)에 정의된 그대로 가정하며 절대 수정하지 않는다.

**Goal:** 조직 Notion workspace의 share-in된 root 페이지 트리를 1회성/증분으로 `org_knowledge` + `kb_sources`에 백필하는 `NotionBackfillAdapter`와 `breadmind kb backfill notion` CLI를 백본 `BackfillJob` 인터페이스 위에 구현한다.

**Architecture:** 백본 `BackfillJob` ABC 위에 얹는 `NotionBackfillAdapter` (`kb/backfill/adapters/notion.py`) — `discover()`는 Notion `POST /v1/search`로 share-in된 페이지 목록을 받고 `blocks.children.list`로 블록 트리를 재귀 평탄화 (max depth 8) + DB row를 일반 page처럼 collapse 한다. 권한 모델은 spec §2.3 share-in 셋 스냅샷(C1의 Notion 해석) — discover 직전 한 번 잡고 mid-run 404는 `skipped["share_revoked"]` 정상 경로. 인증 lookup이 다른 personal adapter(`personal/adapters/notion.py`)와는 클래스를 분리하되, BASE_URL / NOTION_VERSION / `_parse_iso` / 헤더 빌더는 신규 `notion_common.py`로 좁게 추출하여 공유한다.

**Tech Stack:** Python 3.12+, `aiohttp` (personal adapter와 동일 — 신규 SDK 의존 추가 없음, 본문 사전 조사로 `pyproject.toml`에 notion SDK 부재 확인), pytest-asyncio (`asyncio_mode = "auto"`), testcontainers Postgres (e2e).

---

## File Structure

신규/수정 파일과 1줄 책임:

| Path | Status | Responsibility |
|---|---|---|
| `src/breadmind/kb/backfill/adapters/__init__.py` | new | Adapter 패키지 초기화 (re-export `NotionBackfillAdapter`). |
| `src/breadmind/kb/backfill/adapters/notion_common.py` | new | Notion API 공통 상수/헬퍼 (`BASE_URL`, `NOTION_VERSION`, `build_headers`, `parse_iso`) — personal/org 양쪽이 import. |
| `src/breadmind/kb/backfill/adapters/notion.py` | new | `NotionBackfillAdapter` 본체 (`prepare`/`discover`/`filter`/`cursor_of`/`instance_id_of`) + 블록 평탄화 + 시그널 필터. |
| `src/breadmind/kb/backfill/adapters/notion_client.py` | new | `aiohttp` 기반 Notion API client wrapper — 3 rps 토큰 버킷, 429 `Retry-After` + `(60, 300, 1800)` backoff, `search` / `blocks.children.list` / `databases.query` / `pages.retrieve` 호출 표면 노출. |
| `src/breadmind/personal/adapters/notion.py` | modify | `_BASE_URL` / `_NOTION_VERSION` / `_parse_iso` / 헤더 빌더 helper를 `notion_common`에서 import 하도록 변경 (동작 무변경 — regression 가드). |
| `src/breadmind/kb/backfill/cli.py` | modify | 백본이 등록한 `breadmind kb backfill` Click 그룹에 `notion` 서브명령 추가 (백본 CLI 모듈 위치는 백본 plan에 따른다 — 본 task에서는 import만). |
| `tests/kb/backfill/adapters/__init__.py` | new | Adapter 테스트 패키지. |
| `tests/kb/backfill/adapters/test_notion_common.py` | new | `notion_common` helper 단위 테스트 + personal adapter regression import test. |
| `tests/kb/backfill/adapters/test_notion_client.py` | new | API client wrapper (rate limit / 429 / backoff) 단위 테스트. |
| `tests/kb/backfill/adapters/test_notion_discover.py` | new | `discover()` paging / since-until cut / DB row collapse / 블록 평탄화. |
| `tests/kb/backfill/adapters/test_notion_filter.py` | new | §4 시그널 필터 10개 키 각각의 적중 케이스. |
| `tests/kb/backfill/adapters/test_notion_acl.py` | new | share-in 스냅샷 + mid-run 404 → `share_revoked`. |
| `tests/kb/backfill/adapters/test_notion_cli.py` | new | `breadmind kb backfill notion` CLI 인자 / dry-run 출력 골든 스냅샷. |
| `tests/kb/backfill/adapters/notion_fixtures/` | new | recorded Notion API JSON 픽스처 (search / blocks / database query). |

---

## Task 분해 (TDD 2-5분 step)

각 task는 **(1) 실패하는 테스트 추가 → (2) 최소 구현 → (3) refactor + lint + targeted test 통과** 사이클. 모든 task에서 백본의 `BackfillItem` / `JobReport` 시그니처를 **그대로 사용**(필드 추가/제거 금지). `parent_ref`는 `f"<source_kind>:<source_native_id>"` 형식 (백본 §12.7).

---

### Task 1 — Prerequisite gate + `notion_common.py` 추출

- [ ] Sub-project 1 plan의 머지 커밋 SHA를 `git log master --oneline | grep backfill-pipeline-slack` 로 검증. 미머지면 **즉시 중단**하고 caller에게 보고.
- [ ] `src/breadmind/kb/backfill/adapters/notion_common.py` 신규: `BASE_URL = "https://api.notion.com/v1"`, `NOTION_VERSION = "2022-06-28"`, `def build_headers(api_key: str) -> dict[str, str]`, `def parse_iso(value: str | None) -> datetime | None` (현 `personal/adapters/notion.py:13-39`의 동일 로직 추출).
- [ ] `tests/kb/backfill/adapters/test_notion_common.py`: `parse_iso` 의 `Z` → `+00:00` 변환, `None` 입력 통과, `build_headers` 의 3개 키 (`Authorization` / `Notion-Version` / `Content-Type`) 모두 존재 + `Bearer` prefix.
- [ ] `src/breadmind/personal/adapters/notion.py` 수정: 위 4개를 `notion_common`에서 import (모듈 레벨 alias 유지 — 외부 reference 보존). `pytest tests/personal/adapters/test_notion*.py` 통과로 regression 가드.

**Spec coverage:** §9 (`personal`과 공유 가능한 좁은 부분 4개 추출 결정).

---

### Task 2 — Notion API client wrapper (3 rps 토큰 버킷 + 429 backoff)

- [ ] `tests/kb/backfill/adapters/test_notion_client.py`: (1) 연속 호출 3건 사이 `time.monotonic` mock으로 333ms gap 강제, (2) 429 + `Retry-After: 7` → `asyncio.sleep(7)` 후 재시도, (3) `Retry-After` 부재 시 `(60, 300, 1800)` 순서, (4) 5xx 동일 backoff, (5) `asyncio.Semaphore(1)` 로 동시성 1.
- [ ] `src/breadmind/kb/backfill/adapters/notion_client.py`: `class NotionClient` — `aiohttp.ClientSession` 보유, `async def request(method, path, *, json=None) -> dict`, `async def search(...)`, `async def list_block_children(block_id, *, start_cursor=None)`, `async def query_database(db_id, *, start_cursor=None)`, `async def retrieve_page(page_id)`. 토큰 버킷은 `asyncio.Lock` + `last_call: float` + `min_interval=1/3` 단일 인스턴스 상태. 헤더는 `notion_common.build_headers`.
- [ ] 테스트 통과 + `ruff check`.

**Spec coverage:** §5.1 (3 rps 토큰 버킷, 동시성 1, backoff schedule).

---

### Task 3 — `NotionBackfillAdapter.__init__` + `prepare()` (share-in 스냅샷)

- [ ] `tests/kb/backfill/adapters/test_notion_acl.py::test_prepare_snapshots_visible_pages`: fake client가 `search` 응답에 5개 페이지 반환 → `await adapter.prepare()` 후 `adapter._share_in_snapshot: frozenset[str]` 에 5개 page id가 들어있다.
- [ ] `tests/...::test_prepare_propagates_auth_failure`: client가 401 → `PermissionError` raise.
- [ ] `src/breadmind/kb/backfill/adapters/notion.py`: `class NotionBackfillAdapter(BackfillJob)` — `source_kind = "notion_page"`, `__init__(*, org_id, source_filter, since, until, dry_run, token_budget, config=None, client=None, vault=None)`, `async def prepare()`. `prepare()`는 `vault.retrieve(f"notion:org:{org_id}")` → token → `NotionClient` 생성 → `auth.test`-equivalent (Notion에는 `users/me`) 호출로 workspace_id 획득 + `search` 1차로 share-in된 root 페이지 셋 스냅샷.
- [ ] `instance_id_of(source_filter) -> str`: workspace_id (prepare 캐시값) 반환. workspace_id가 source_filter에서 미지정이면 `users/me` 응답의 `bot.workspace_id` 사용.

**Spec coverage:** §2.2 (token vault key `notion:org:<project_id>`), §2.3 (share-in 스냅샷 시점), C1 적용, D5 (`instance_id_of`).

---

### Task 4 — `discover()` Phase A: search-based root page 목록 + since/until client-side cut

- [ ] `tests/...test_notion_discover.py::test_search_paginates_and_cuts_until`: fake client가 2 페이지 search 응답 (`has_more=true` → `next_cursor`) 반환. `since=2026-01-01`, `until=2026-04-01` 일 때 `last_edited_time` 기준 cut 후 yield 카운트 확인.
- [ ] `tests/...::test_search_stops_when_older_than_since`: search response가 `desc` 정렬이므로 `since` 보다 오래된 첫 페이지 만나면 즉시 break.
- [ ] `discover()` 구현: `search` (`filter={"value":"page","property":"object"}`, `sort={"timestamp":"last_edited_time","direction":"descending"}`) + 페이지마다 `since <= last_edited_time < until` 적용 후 yield. 페이지마다 `BackfillItem` 의 `source_kind="notion_page"`, `source_native_id=page_id`, `source_uri=page["url"]`, `source_created_at=parse_iso(page["created_time"])`, `source_updated_at=parse_iso(page["last_edited_time"])`, `parent_ref` (parent.type 분기 — workspace면 None, page_id이면 `f"notion_page:{parent_id}"`, database_id이면 `f"notion_database:{parent_id}"`), `author=page["created_by"]["id"]`.

**Spec coverage:** D4 (어댑터 client-side cut), §6.1 (search 1차 / sitemap fallback Phase 3), §3.0 (`BackfillItem` 채움 규약 D3/D6 정렬).

---

### Task 5 — `discover()` Phase B: 블록 트리 평탄화 (markdown 본문)

- [ ] `tests/...test_notion_discover.py::test_block_tree_flatten_all_types`: §3.2 표의 모든 블록 타입 1개씩 담은 fixture → markdown round-trip. `paragraph` / `heading_1..3` / `bulleted_list_item` / `numbered_list_item` / `to_do` (체크박스 `[x]` 보존) / `code` (language 보존) / `toggle` (들여쓰기) / `quote` / `callout` / `table`+`table_row` (GitHub pipe) / `equation` (`$$..$$`) / `divider` (drop) / `image|file|pdf|video|audio|bookmark` (`[file: <caption>]`) / `synced_block` (원본만 1회) / `column_list|column` (단순 concat).
- [ ] `tests/...::test_block_tree_depth_capped_at_8`: 9단 중첩 fixture → 8단까지 평탄화 + truncation marker 라인.
- [ ] `tests/...::test_child_page_block_not_recursed`: `child_page` 블록은 본문 평탄화에서 제외 (별도 search 결과로 잡힘).
- [ ] `tests/...::test_child_database_queues_db_id`: `child_database` 블록은 별도 enumeration entry로 큐잉됨.
- [ ] 구현: `_flatten_blocks(client, root_block_id, depth=0) -> str` — 재귀 호출, depth 8 cap, 평탄화 후 `BackfillItem.body`에 채움. `estimated_tokens = len(body) // 4` 도 채움 (`extra` 가 아닌 `BackfillItem` 표준 필드 — 백본 plan에서 정의된 위치 그대로).

**Spec coverage:** §3.2 전체 표, §1 P3 (file placeholder).

---

### Task 6 — `discover()` Phase C: Database 처리 (메타 인덱스 페이지 + row collapse)

- [ ] `tests/...::test_database_meta_emits_index_page`: search 결과에 `object: "database"`가 포함되면 1개의 "DB 인덱스 페이지" `BackfillItem` 으로 변환 (title=DB title, body=description + property 스키마 요약).
- [ ] `tests/...::test_database_rows_via_query`: `databases.query` 페이지네이션 → 각 row를 일반 page와 동일하게 처리. row의 `parent_ref = f"notion_database:{db_id}"` 정확히 채움.
- [ ] `tests/...::test_inline_child_database_in_page_queues_rows`: 페이지 본문의 `child_database` 블록 → 별도 row 백필 큐잉 (Phase 1 정책: row마다 분리).
- [ ] 구현: discover에서 search response의 `object` 값을 분기. `inline databases (rows queued: N)` 카운트를 `JobProgress.extra` 또는 dry-run report 라인 누적기에 기록 (백본 `JobProgress`에 신규 필드 추가 금지 — 어댑터 로컬 카운터로 보유 후 `JobReport.skipped`/dry-run 텍스트 빌더에서 합산).

**Spec coverage:** §1 (P1 DB / `child_database`), §3.3, §11.2 Q4 (collapse 옵션은 Phase 2.1 — 본 plan 범위 외 명시).

---

### Task 7 — `cursor_of(item)` 인코딩 (`last_edited_time:page_id`)

- [ ] `tests/...::test_cursor_of_format`: `BackfillItem` (last_edited_time=`2026-03-15T08:30:00Z`, source_native_id=`a1b2...`) → `cursor_of(item) == "2026-03-15T08:30:00+00:00:a1b2..."`.
- [ ] `tests/...::test_cursor_of_monotonic`: 두 아이템 (older / newer) 의 cursor 가 문자열 정렬에서도 단조.
- [ ] 구현: `def cursor_of(self, item: BackfillItem) -> str: return f"{item.source_updated_at.isoformat()}:{item.source_native_id}"`. 백본은 opaque 처리.
- [ ] resume 경로: `_cursor_to_iso(cursor: str) -> datetime` private — `discover()`가 resume 시 `since = max(self.since, _cursor_to_iso(last_cursor))` 로 적용.

**Spec coverage:** D2 (opaque cursor + adapter 인코딩 책임), §6.1.

---

### Task 8 — `filter()` — Notion-특화 10개 `skipped` 키 + 평가 순서

- [ ] `tests/...test_notion_filter.py`: 10개 키 각각 1개 케이스 + 룰 평가 순서 verification (한 페이지가 2개 룰에 걸리면 §4 우선순위에 따라 첫 번째만 카운트).
  - `archived` (page.archived=true)
  - `in_trash` (page.in_trash=true)
  - `template` (parent.template=true OR title prefix `Template:`)
  - `acl_lock` (page_id ∉ self._share_in_snapshot — Notion 모델상 보통 0이지만 키 유지)
  - `share_revoked` (Task 9에서 검증; 본 task에서는 키 등록만)
  - `title_only` (block 0개 + title만)
  - `empty_page` (markdown body whitespace 제외 길이 < 120)
  - `oversized` (markdown > 200,000 chars — split + audit log 1줄 후 `False` 반환)
  - `duplicate_body` (`(project_id, title, body_hash)` 조회 — `extra["_dup_check"]` 키로 runner에 위임 vs 어댑터 자체 조회 — **결정: 어댑터가 보유한 in-run set으로 본문 hash 누적, 같은 run 내 중복만 카운트**. cross-run 중복은 백본의 `uq_org_knowledge_source_native` 가 처리.)
  - `redact_dropped` (Sub-project 1 redact 단계 산출 — 본 어댑터 filter에서는 카운트 안 함, 키만 백본 dashboard 호환용으로 spec에 명시).
- [ ] 구현: `filter(item)` 은 sync (백본 invariant). 룰을 §4 평가 순서대로 if-elif. drop 시 `item.extra["_skip_reason"] = "<key>"` 후 `False` 반환 (백본 runner 가 카운트). 임의 신규 키 추가 금지.

**Spec coverage:** §4 전체 표 + 평가 순서 단락.

---

### Task 9 — Mid-run 404 → `skipped["share_revoked"]`

- [ ] `tests/...test_notion_acl.py::test_mid_run_404_is_share_revoked`: discover가 페이지 fetch 시 404 → 해당 page는 `extra["_skip_reason"] = "share_revoked"` + `False` 반환 (예외 propagate 금지).
- [ ] 구현: `discover()` 의 페이지별 try/except — `aiohttp.ClientResponseError` status==404 catch → audit log 1줄 + skip. share-in 풀린 페이지의 자손 fetch 시 404도 동일.

**Spec coverage:** C1 Notion 해석, §2.3, §4 `share_revoked` 키.

---

### Task 10 — Failure isolation (페이지 단위 try/except)

- [ ] `tests/...::test_per_page_error_does_not_abort_run`: 5개 페이지 중 3번째에서 `RuntimeError` → `JobReport.errors += 1` + `(page_id, reason)` log + 4/5번째 정상 처리.
- [ ] 구현: `discover()` 페이지 루프 try/except (404 제외 — 404는 `share_revoked`). 백본 runner 의 `errors > 0.10 * discovered` 임계는 백본이 처리.

**Spec coverage:** §6.4 (Failure Isolation).

---

### Task 11 — CLI `breadmind kb backfill notion` 서브명령 등록

- [ ] `tests/...test_notion_cli.py::test_cli_args_parse`: `--org <uuid> --workspace pilot-alpha --since 2026-01-01 --until 2026-04-01 --token-budget 2000000 --dry-run` → 인자 파싱 성공.
- [ ] `tests/...::test_cli_org_uuid_validation`: `--org` 가 UUID 아니면 종료 코드 1.
- [ ] `tests/...::test_cli_default_since_is_last_cursor_or_epoch`: `--since` 미지정 시 `connector_configs.last_cursor` 또는 1970-01-01.
- [ ] `tests/...::test_cli_exit_codes`: 정상 0 / budget exceeded 2 / auth fail 3 / 기타 1.
- [ ] 구현: `src/breadmind/kb/backfill/cli.py` 의 백본 Click 그룹에 `@cli.command("notion")` 추가. 내부적으로 `NotionBackfillAdapter` 인스턴스화 → `BackfillRunner.run(adapter)` → `JobReport` 반환 → §7 텍스트 렌더 (Task 12).

**Spec coverage:** §8 (CLI Entry Point) 전체.

---

### Task 12 — Dry-run 출력 (spec §7 정확 일치)

- [ ] `tests/...test_notion_cli.py::test_dry_run_output_matches_spec`: spec §7 예시 문자열을 골든 스냅샷으로 저장. fake report 입력 → 라인 단위 일치.
- [ ] 출력 라인 (필수, 순서 고정):
  - `[notion-backfill] org=... workspace=... since=... until=now`
  - `[notion-backfill] discover via Notion search ...`
  - `discovered pages` / `in scope after filter`
  - `skipped[archived|template|empty_page|in_trash|duplicate_body]` (0이어도 출력 — share-in 풀린 root 수 표시 위해 `skipped[share_revoked]` 도 0 라인 포함)
  - `inline databases : N (rows queued: M)`
  - `estimated tokens (input)` + run budget + org month ceiling + `[OK]` / `[BUDGET EXCEEDED]`
  - `estimated chunks` / `estimated embed cost` / `estimated wall-clock` (3 rps 가정)
  - `rate limit : 3 rps, hourly budget 1000 pages (instance=workspace <label>)`
  - `redact policy : kb/redactor.py default (vocab=org-<label>)`
  - `permission lock : share-in snapshot @ discover start (C1)` + `(N pages visible to integration; mid-run 404 → skipped[share_revoked])`
  - `cursor format : last_edited_time:page_id (D2, opaque to backbone)`
  - `[notion-backfill] DRY RUN — no rows written. Re-run without --dry-run to ingest.`

**Spec coverage:** §7 전체 (운영자 검토용 단일 텍스트 포맷).

---

### Task 13 — Token budget 초과 fail-closed (P1 ceiling + per-job budget)

- [ ] `tests/...::test_dry_run_exceeds_budget_returns_exit_2`: dry-run 에서 `estimated_tokens > token_budget` → 텍스트에 `[BUDGET EXCEEDED]` + 종료 코드 2.
- [ ] `tests/...::test_dry_run_exceeds_org_month_ceiling_returns_exit_2`: `estimated_tokens + tokens_used > tokens_ceiling` → 동일.
- [ ] `tests/...::test_ingest_mid_run_ceiling_pause`: ingest 중 `OrgMonthlyBudgetExceeded` → 마지막 안전 cursor 보존 후 `status='paused'` (백본 runner 가 처리; 어댑터는 cursor 만 정확히 제공).
- [ ] 구현: dry-run 진입 시 어댑터의 `estimated_tokens` 합산 → 백본의 `OrgMonthlyBudget.would_exceed()` 호출 → 초과 시 텍스트 + 종료 코드 2 반환. 자동 trim 금지.

**Spec coverage:** §5.3 (백본 P1 ceiling + P4 fail-closed 일관성).

---

### Task 14 — `HourlyPageBudget` instance-keyed 통합 (D5)

- [ ] `tests/...::test_hourly_budget_keyed_by_workspace_id`: 같은 org가 두 workspace 를 share-in 한 경우 `HourlyPageBudget.consume(project_id, instance_id=workspace_id_a)` 와 `instance_id=workspace_id_b` 가 분리 카운트.
- [ ] `tests/...::test_hourly_budget_pause_preserves_cursor`: budget 초과 시 `BudgetExceeded` raise → 백본 runner 가 `paused` + last_cursor 보존 (어댑터는 cursor 정확성만 검증).
- [ ] 구현: `discover()` 매 페이지 yield 직전 `await self._budget.consume(self.org_id, instance_id=self._workspace_id)`. legacy `(org_id,)` 키는 사용 안 함 (백본 invariant 5).

**Spec coverage:** D5, §5.2.

---

### Task 15 — E2E (가짜 Notion API fixture + testcontainers Postgres)

- [ ] `tests/kb/backfill/adapters/notion_fixtures/` 에 search 응답 (15 페이지, 일부는 archived/template/empty), `blocks.children.list` 응답 (3개 페이지 분), `databases.query` 응답 (1 DB, 5 row) recorded JSON 배치.
- [ ] `tests/...::test_e2e_dry_run_estimates_match_real_run` (testcontainers Postgres + 백본 migration `010_kb_backfill` 적용): fake `NotionClient` 가 fixture 반환. dry-run 카운터 == 실 ingest 후 `org_knowledge` row 수 (±skipped) ±5%.
- [ ] `tests/...::test_e2e_idempotency`: 동일 fixture 두 번 ingest → row 동일, body_hash 동일 → no-op (`uq_org_knowledge_source_native` 작동).
- [ ] `tests/...::test_e2e_resume_from_cursor`: 5번째 페이지에서 강제 종료 → resume → 6번째부터 처리, 최종 row 수 동일.
- [ ] 구현: 새 코드 최소 — fixture loader + fake client 만 추가. coverage 목표: `kb/backfill/adapters/notion.py` ≥ 90%.

**Spec coverage:** §10 (테스트 전략 — Unit + Integration + E2E optional).

---

## Self-Review Checklist (실행 전 / 실행 중 모두 통과)

### 1. Spec coverage (§1~§9 모두 task 매핑) — fail 없음 확인

- §1 Overview (P0~P3 우선순위) → Task 4, 5, 6 (P0/P1), Task 5의 file placeholder (P3), Task 6 (DB).
- §2 인증/권한 → Task 3 (vault key + share-in 스냅샷).
- §3 데이터 매핑 (3.0 BackfillItem / 3.1 org_knowledge / 3.2 블록 / 3.3 DB) → Task 4 (필드 채움), Task 5 (블록), Task 6 (DB).
- §4 시그널 필터 + 평가 순서 → Task 8.
- §5 Rate limit (5.1 토큰 버킷 / 5.2 instance / 5.3 budget) → Task 2 (5.1), Task 14 (5.2), Task 13 (5.3).
- §6 Backfill 흐름 (6.1 discover / 6.2 단계 / 6.3 idempotency / 6.4 failure isolation) → Task 4 (6.1), Task 11 (6.2 — runner 호출), Task 15 (6.3), Task 10 (6.4).
- §7 Dry-run 출력 → Task 12 (골든 스냅샷).
- §8 CLI → Task 11.
- §9 personal과 분리 → Task 1 (helper만 추출, 본체 분리 결정).

### 2. Placeholder scan

- "TBD" / "TODO" / "FIXME" / "<placeholder>" 텍스트가 plan 본문에 0건 — 본 plan 자체에서 fail.
- 모든 Task의 테스트 케이스와 구현 단계가 구체 함수명/파일명/예외명/숫자임계로 명시.

### 3. Type consistency (백본 + Notion 어댑터 시그니처 drift 방지)

- `BackfillItem` 필드: `source_kind` / `source_native_id` / `source_uri` / `source_created_at` / `source_updated_at` / `title` / `body` / `author` / `parent_ref` / `extra` — 백본 §3 정의 그대로. 본 plan에서 신규 필드 추가/제거/이름변경 0건.
- `JobReport.skipped: dict[str, int]` — 어댑터는 키 등록만, runner가 카운트 (백본 invariant 3).
- `cursor_of(item) -> str` 시그니처 / `instance_id_of(source_filter) -> str` 시그니처 — 백본과 일치.
- `filter(item) -> bool` sync — 백본 invariant. async/API 호출 금지 (Task 8).

### 4. share-in 권한 모델 일관성

- ACL task (Task 3 prepare snapshot, Task 8 acl_lock 카운터, Task 9 share_revoked mid-run) 3곳 모두 "share-in 셋"이 단일 출처 (`self._share_in_snapshot: frozenset[str]`).
- 활성 멤버 비교 (백본 C1 원본) **사용 안 함** — Notion 모델상 부적용 (spec §2.3).
- `acl_lock` 키는 보통 0 카운트지만 백본 dashboard 호환 위해 등록만 (spec §4 마지막 단락).

### 5. Notion-특화 skipped 10개 키 모두 등장 확인

`archived` / `in_trash` / `template` / `empty_page` / `title_only` / `oversized` / `duplicate_body` / `share_revoked` / `acl_lock` / `redact_dropped` — Task 8/9 에서 모두 명시.

### 6. 백본 의존 컴포넌트 import 명세

| 백본 컴포넌트 | 본 plan 사용 위치 |
|---|---|
| `BackfillJob` (ABC) | Task 3 (`NotionBackfillAdapter(BackfillJob)`) |
| `BackfillItem` (frozen dataclass) | Task 4-6 (yield), Task 7 (cursor_of 입력), Task 8 (filter 입력) |
| `JobReport` / `JobProgress` | Task 11 (CLI 렌더), Task 12 (dry-run), Task 15 (e2e 검증) |
| `BackfillRunner` | Task 11 (`runner.run(adapter)`) |
| `HourlyPageBudget` (instance-keyed) | Task 14 |
| `OrgMonthlyBudget` (P1 ceiling) | Task 13 |
| `Redactor.abort_if_secrets()` / `Redactor.redact()` | runner가 호출 — 본 plan은 의존만, 직접 호출 금지 (백본 invariant) |
| `EmbeddingService` | runner가 호출 — 동상 |
| `kb_backfill_jobs` / `kb_backfill_org_budget` 테이블 | Task 15 (testcontainers migration `010_kb_backfill`) |
| Notion 전용 `connector_configs.scope_key = "notion:<workspace>"` | Task 11 (CLI default `since` lookup) |

본 plan은 백본의 어떤 시그니처/스키마도 수정하지 않는다. 백본이 변경되면 본 plan이 따라가는 단방향 의존.

---

## Out of scope (본 plan 미포함, 후속 spec)

- Notion comments (P2) — Phase 2 fast-follow 또는 Phase 3.
- 첨부파일 / 이미지 OCR (P3) — Phase 3 별도 spec.
- Public OAuth (3-legged) — Phase 3.
- DB row collapse opt-in (`databases.<id>.collapse=true`) — Phase 2.1.
- Sitemap-style discover fallback — Phase 3.
- Web UI — 백본과 동일하게 deferred.
