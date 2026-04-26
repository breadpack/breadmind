# Backfill Mode for Confluence Connector — Design Spec

**작성일:** 2026-04-26
**Sub-project:** 3 of 3 (Confluence adapter for the common BackfillJob pipeline)
**상태:** Draft (read-only investigation; no code change in this spec)
**전제 master tip:** `a2d6111` (org_id Phase 2 v2 wiring 완료)
**대상 파일:** `src/breadmind/kb/connectors/confluence.py` (extend, do not break)

> Sub-project 1에서 공통 `BackfillJob` 파이프라인이 별도 agent에 의해 동시
> 설계 중. 본 spec은 **기존 Confluence connector를 그 파이프라인의 어댑터로
> 확장**하는 데에만 집중한다. `BackfillJob` 본체의 인터페이스/스케줄링/리포팅
> 은 Sub-project 1 spec의 결정을 따르며, 충돌 가능성은 §10 Open Questions에
> 적는다.
>
> **백본 인터페이스 합의 (Sub-project 1):**
> - **D1.** `JobReport.skipped: dict[str, int]` — 사유별 카운터. Confluence
>   특화 키: `"empty_page"`, `"archived"`, `"restricted"`, `"draft"`,
>   `"attachment_only"`, `"acl_lock"`.
> - **D2.** `JobReport.cursor: str | None` — opaque token. Confluence는
>   `last_modified:content_id` 또는 `next_link` 인코딩 권장.
> - **D3.** `BackfillItem.parent_ref: str | None` — Confluence section /
>   subpage 부모 페이지 id. 데이터 매핑 §3에서 사용.
> - **D4.** `since/until` 필터는 어댑터 책임 — Confluence Cloud는 CQL의
>   `lastModified >= "..." AND lastModified < "..."` 로 server-side filter.
> - **D5.** `HourlyPageBudget` 에 instance-keyed 차원 추가 — Confluence는
>   `instance_id_of(source_filter) -> base_url_hash` (클라우드 site URL
>   또는 on-prem 호스트 hash).
> - **D6.** timestamp 2개 매핑 — `source_created_at = page.history.createdDate`,
>   `source_updated_at = page.version.when` 둘 다 보존.
>
> **Cross-cutting 결정:**
> - **C1.** 권한 락 시점 — discover 시작 직전 활성 멤버 셋 스냅샷 + per-item
>   ACL 표시. Confluence는 `restrictions.read` expand 한 번으로 가져와 활성
>   멤버 집합과 교차 (N+1 회피 위해 expand만 사용).
> - **C2.** 어댑터 클래스 명명 — `ConfluenceBackfillAdapter` **신규 클래스**
>   로 통일. 기존 `ConfluenceConnector` (incremental) 와 분리하여 incremental
>   경로를 깨지 않음.
>
> **운영 정책:** per-org 월 token ceiling 도입 — Confluence 어댑터도 따름.

---

## 1. Overview

### 1.1 현재 connector 상태 (`confluence.py` 기준)

`ConfluenceConnector(BaseConnector)`는 **incremental 폴링**만 지원한다.

- 입력: `project_id, scope_key=<spaceKey>, cursor=<ISO 8601 timestamp>`
- 흐름: `_fetch_pages(spaceKey, cursor) → html_to_markdown → _chunk_markdown
  → extractor.extract → review_queue.enqueue` + `_scan_retirements`.
- API: `GET {base_url}/rest/api/content?spaceKey=<key>&updated-since=<cursor>
  &expand=body.storage,version`, `limit=50`, `_links.next` 페이지네이션.
- Auth: vault에서 `email:api_token` 꺼내 base64 → `Basic ...`.
- Rate / 재시도: 429 / 5xx에 대해 `Retry-After` + `(60, 300, 1800)s` 백오프
  (`_get_with_retry`).
- 예산: `HourlyPageBudget` (sliding 1h, 기본 1000 페이지/project).
- 메트릭: 매 sync 종료 후 `refresh_size_metric()`로 `breadmind_kb_size_bytes`
  갱신.
- 메타: `SourceMeta(source_type="confluence", extracted_from="confluence_sync"
  | "confluence_retirement")`.
- 상태: `BaseConnector.sync` 가 `connector_sync_state` 테이블에 cursor +
  status 저장.

### 1.2 Backfill 모드 추가의 의미

Incremental 폴링은 "오늘 이후 변경된 페이지"만 본다. 운영자가 **신규 파일럿
온보딩 / KB 재구축 / 누락 공간 일괄 흡수** 같은 일회성 대량 적재를 하려면:

- `updated-since=`를 안 주고 전체를 가져오게 하면 cursor가 깨지고, 다음
  incremental run이 "전체 다시"가 된다.
- 페이지 수가 `HourlyPageBudget` 기본값을 쉽게 초과한다.
- redaction / 시그널 필터 / token_budget 같은 backfill 전용 가드가 없다.

따라서 **별도 진입점**으로 `BackfillJob` 파이프라인의 *connector 어댑터* 인
"backfill 모드"를 추가한다. 기존 `_do_sync` 경로는 **건드리지 않는다** (호환성
+ scheduler 회귀 0).

---

## 2. Gap 분석 — incremental ↔ backfill

| 항목 | 현재 incremental | Backfill 모드 (추가분) |
|---|---|---|
| 진입점 | `BaseConnector.sync(project_id, scope_key)` | `BackfillJob.run(adapter=ConfluenceBackfillAdapter(...), ...)` (C2: 신규 클래스) |
| 시간창 | `cursor` 단방향 (since only) | `since`/`until` 양방향 윈도우 |
| 검색 방식 | `GET /rest/api/content?spaceKey=&updated-since=` | **CQL** `GET /rest/api/content/search?cql=...` (공간 + 날짜 범위 + type=page 조합) |
| 페이지네이션 | `_links.next` (그대로 재사용) | 동일 — but `start`/`limit` cursor도 허용 (CQL endpoint 호환) |
| 단위 | space 1개 | space 다중 / 특정 page id 리스트 / label / parent subtree |
| Cursor 저장 | `connector_sync_state.last_cursor` (write) | **write 안 함** — backfill은 cursor를 오염시키면 안 됨 |
| 예산 | `HourlyPageBudget` (소프트 가드) | `token_budget` (BackfillJob 전역) + `HourlyPageBudget` 둘 다 적용 |
| Redaction | extractor 내부 로직만 | `kb/redactor.py`로 명시적 단계 (`redact` 단계) |
| Dry-run | 없음 | 1급 — 실제 enqueue 안 하고 JobReport만 만든다 |
| Retirement scan | 매 sync 종료 후 자동 | **수행 안 함** (backfill은 신규 적재 전용) |
| 출력 | `SyncResult(new_cursor, processed, errors)` | `JobReport`(공통 스키마) — counts + sample skip reasons + token spend |

### 2.1 CQL? `/content`?

- `/wiki/rest/api/content?spaceKey=&updated-since=` 는 단방향이라 backfill의
  `since/until`을 못 표현 → **CQL 사용 권고** (D4: server-side filter는
  어댑터 책임):
  `space=<KEY> AND type=page AND lastModified >= "<since>" AND lastModified < "<until>"`
  (반열림 `[since, until)`).
  추가 필터는 CQL 쪽에 자연스럽게 얹힌다 (`label != "draft"` 등 §4 참고).
- CQL 응답 스키마는 `_links.next`가 동일하게 있어 기존 `_get_with_retry` +
  pagination 루프를 재사용 가능. `expand=body.storage,version,restrictions,
  history` 추가만 하면 된다.
- 단, CQL은 `limit` 상한 25~100 사이로 제공자 정책에 따라 다름 → 어댑터에서
  `_PAGE_LIMIT=50`을 그대로 쓰되, 응답이 비면 종료한다.

---

## 3. 데이터 매핑 — Confluence page → `org_knowledge` row

`org_knowledge` 스키마(요약, conftest 기준):

```
id, project_id, title, body, category, source_channel, tags,
embedding, tsv, promoted_from, promoted_by, promoted_at,
revision, superseded_by, rank_weight, flag_count, created_at
```

Backfill에서의 매핑 (Sub-project 1 합의: source-side 타임스탬프 2개 보존
— D6):

`BackfillItem` (백본 스키마, D3 반영):

```python
@dataclass
class BackfillItem:
    source_ref: str               # page.id
    parent_ref: str | None        # D3: page.ancestors[-1].id (subpage/section 부모)
    title: str
    body: str
    tags: list[str]
    source_created_at: datetime   # D6: page.history.createdDate
    source_updated_at: datetime   # D6: page.version.when
    acl: AclMark                  # C1: per-item ACL 표시 (drop / restricted / public)
    raw: dict                     # 원본 page payload (디버그)
```

`org_knowledge` 매핑:

| `org_knowledge` 컬럼 | Confluence 필드 |
|---|---|
| `project_id` | BackfillJob `org_id` (UUID, `org_projects.id`) |
| `title` | `page.title` (markdownify 전, plain) |
| `body` | `html_to_markdown(page.body.storage.value)` — chunked |
| `category` | extractor 결정 (기존 incremental과 동일) |
| `source_channel` | `f"confluence:{spaceKey}"` |
| `tags` | `page.metadata.labels[*].name` (CQL `expand=metadata.labels` 추가) |
| `created_at` | **`page.history.createdDate`** = `source_created_at` (D6) |
| (별도 필드) | `source_updated_at = page.version.when` (D6) — rank_weight 결정에서 활용, §12 risk 참조 |
| `parent_ref` | **D3**: `page.ancestors[-1].id` (subtree 복원용, retriever 컨텍스트) |
| `promoted_from` | `"backfill"` (incremental은 `"sync"`) |
| `revision` | 1 (backfill은 항상 신규; 중복은 §6.3에서 별도 처리) |

`kb_sources` 행:

| 컬럼 | 값 |
|---|---|
| `source_type` | `"confluence"` |
| `source_uri` | `f"{base_url}{web_url}"` (resolved) |
| `source_ref` | `page.id` |
| `captured_at` | `now()` (DB default) |

`SourceMeta.extracted_from = "confluence_backfill"` — incremental의
`"confluence_sync"`와 구분해서 **kb_audit_log / 디버그 추적**이 가능하게
한다.

### 3.1 body view vs storage 포맷

기존 incremental은 `expand=body.storage` 만 사용 → backfill도 **storage
포맷 유지**.
- `view`는 macro가 렌더된 HTML (e.g. JIRA macro → 표). 보기는 좋지만 매크로
  결과가 시점 의존적이라 KB의 "사실"로는 부적합.
- `storage`는 Confluence storage XHTML — markdownify가 이미 처리 중이고,
  매크로는 placeholder로 남는다 (KB 검색에 노이즈가 적음).
- 결정: **storage 유지**. view 도입은 §10 Open Question Q-CF-3.

---

## 4. 시그널 필터 (Confluence 특화)

`BackfillJob`의 `filter` 단계에서 어댑터가 제공하는 조건자(predicate). 모든
조건은 **CQL 우선, 응답 후 보강 필터** 순서로 적용 (네트워크 절감).

| 신호 | 정의 | 처리 위치 |
|---|---|---|
| empty | `len(strip(markdown)) < 50 chars` | post-fetch (markdownify 후) |
| archived | `space.status = "archived"` 또는 `page.metadata.archived = true` | CQL: `space.status != "archived"` |
| restricted | `restrictions.read.users` or `restrictions.read.groups` 비어있지 않음 → §5에서 별도 처리 (lock 적용 / drop 결정) | post-fetch (`expand=restrictions.read`) |
| draft | `page.status != "current"` (draft / trashed) | CQL: `type=page AND status=current` |
| attachment-only | body가 비고 `/child/attachment` 만 존재 | post-fetch |
| comment-only | macro `comment`만 있고 contentful node 없음 | post-fetch (보조) |
| size 초과 | `body_bytes > 256KB` | post-fetch — chunking 시도 후 그래도 chunk 수 > 64면 skip |

skip된 항목은 `JobReport.skipped[reason] += 1` + 처음 N개의 sample (page id,
title) 만 보존 (Sub-project 1 합의: dry-run 출력 가독성).

---

## 5. 권한 락 (page restrictions → 활성 멤버 기반 lock)

합의 (**C1**): **권한 락 시점은 discover 시작 직전**. discover 직전에 활성
멤버 셋 `M` 을 **단일 스냅샷**으로 떠서 backfill run 전체 동안 고정. 과거
시점 ACL 재현 X. per-item 으로는 ACL 표시(`AclMark`)만 부착.

Confluence page restrictions는 두 종류:
- `restrictions.read` = 읽기 제한 (있으면 모든 비멤버는 못 봄)
- `restrictions.update` = 편집 제한 (KB ingest와 무관)

처리 규칙:

1. **discover 시작 직전 스냅샷** (C1): `M = active_members(org_id)` 한 번
   조회. run 동안 mutate 안 함.
2. `expand=restrictions.read` 로 페이지를 가져옴 (C1: 한 번의 expand로
   끝내고 N+1 회피).
3. `restrictions.read.users` 또는 `restrictions.read.groups` 가 **하나라도 있으면**:
   - 페이지 허용 사용자 집합 `P` 와 `M ∩ P` 가 비어있으면 → **drop**
     (`AclMark.DROP`, `JobReport.skipped["acl_lock"] += 1` — D1 키와 일치).
   - 비어있지 않으면 → `AclMark.RESTRICTED` 로 마크하고 `org_knowledge` 에
     적재. retriever 단계 visibility 는 `source_channel` 우회
     (`f"confluence:{space}:restricted"`); 정식 컬럼은 §10 Q-CF-2.
4. restrictions가 없으면 → `AclMark.PUBLIC` (`source_channel = f"confluence:{space}"`).

이 규칙은 incremental connector의 기존 동작과 충돌하지 않는다 (incremental은
restrictions를 expand하지 않으므로 자연스럽게 "뒤늦게 restrict된 페이지는
다음 sync에서 retire" 흐름을 따름; backfill은 first-pass 시점에 강하게
필터링한다는 차이만 있음).

### 5.1 Rate-limit / 예산 차원 (D5)

`HourlyPageBudget` 은 **`(org_id, instance_id)` 2-tuple keyed**.

```python
def instance_id_of(source_filter) -> str:
    # base_url 은 vault 의 confluence credential 에서 결정.
    # cloud: "https://<tenant>.atlassian.net/wiki"
    # on-prem: "https://confluence.acme.internal"
    return sha256(base_url.encode()).hexdigest()[:16]  # base_url_hash
```

같은 org이라도 cloud + on-prem을 동시에 backfill하면 **각 instance별로
독립 budget**이 적용된다 (서로 다른 site의 rate-limit이 겹치지 않도록).

---

## 6. Backfill 흐름

### 6.1 source_filter 형태

`source_filter` 는 Sub-project 1의 공통 필드. Confluence 어댑터는 다음
값을 받는다:

```yaml
# space 단위 (가장 일반적)
source_filter:
  kind: space
  spaces: ["ENG", "OPS"]      # 1개 이상
  labels_exclude: ["draft", "wip"]   # CQL: NOT label = ...

# 페이지 단위 (이미 알고 있는 page id 묶음)
source_filter:
  kind: page_ids
  ids: ["12345", "67890"]

# subtree 단위 (특정 부모 아래 전부)
source_filter:
  kind: subtree
  root_page_id: "23456"
```

내부 매핑:
- `kind=space` → CQL `space in ("ENG","OPS") AND type=page AND status=current`
- `kind=page_ids` → 각 id별 `GET /rest/api/content/{id}?expand=...`
- `kind=subtree` → CQL `ancestor = "23456" AND type=page AND status=current`

### 6.2 단계 매핑 (BackfillJob lifecycle)

`ConfluenceBackfillAdapter` (C2) 가 백본의 단계별 콜백을 구현:

| 단계 | Confluence 어댑터 동작 |
|---|---|
| (run init) | C1: `M = active_members(org_id)` 스냅샷 / D5: `instance_id` 결정 |
| discover | source_filter → CQL/REST 페이지네이션 (D4: server-side `since/until`), `BackfillItem` yield (D3 parent_ref + D6 timestamps 포함) |
| filter | §4 시그널 + §5 restrictions → keep / skip + reason (D1 키) |
| redact | `redactor.redact(markdown)` (이미 chunk되기 전 raw markdown 단위로) |
| embed | 기존 embedding 모듈 (incremental과 같은 코드 경로) |
| store | `org_knowledge` + `kb_sources` insert. dry_run=True면 SQL 실행 안 함 |
| (run end) | `JobReport` 생성: `skipped: dict[str, int]` (D1), `cursor: str \| None` (D2), `terminated_by`, sample skips |

`JobReport.cursor` (D2) 인코딩 규칙: 부분 종료 시 `"<lastModified_iso>:<page_id>"`
형태. resume시 CQL `lastModified > "<iso>" OR (lastModified = "<iso>" AND id > "<page_id>")`.

### 6.3 중복 / 멱등성

- 같은 `(source_type='confluence', source_ref=page.id, project_id)`가 이미
  `kb_sources` ↔ `org_knowledge` 에 있으면 **skip** (`JobReport.skipped["already_ingested"] += 1`).
  강제 재적재는 `--reingest` 플래그(§7)로만 허용 (기존 row를
  `superseded_by`로 처리하는 길은 §10 Q-CF-4).

### 6.4 재시도 / 실패 격리

기존 `_get_with_retry`(429/5xx + Retry-After) 로직을 그대로 재사용. 페이지
단위 예외는 **`JobReport.errors[]`** 에 page id + 사유로만 기록하고 진행을
멈추지 않는다 (incremental의 `_do_sync` 와 같은 정책).

전역 종료 조건:
- `token_budget` 소진 (run-level) — graceful stop, JobReport에 `terminated_by="token_budget"`.
- **per-org 월 token ceiling** (운영 정책) 초과 — `terminated_by="org_monthly_ceiling"`.
  Confluence 어댑터는 백본이 강제하는 ceiling 을 그대로 따른다 (어댑터에는
  별도 추적 없음).
- `HourlyPageBudget` 초과 (D5: instance-keyed) — `terminated_by="hourly_budget"`.
- 사용자 cancel (Sub-project 1 입력 채널) — `terminated_by="cancelled"`.

부분 종료 시 `JobReport.cursor` (D2) 가 채워지면 다음 run에서 `--resume`
플래그(§7) 로 이어서 처리 가능.

---

## 7. CLI 엔트리포인트

```
breadmind kb backfill confluence \
  --org <uuid|slug> \
  --space ENG [--space OPS] \
  --since 2024-01-01 --until 2026-04-26 \
  [--page-ids 12345,67890] \
  [--token-budget 1000000] \
  [--dry-run] \
  [--reingest] \
  [--resume <cursor>]
```

- `--org` : `org_projects.id` UUID 또는 slug. 내부 resolver가 둘 다 받음
  (org_id Phase 2 v2 패턴 답습).
- `--space` : 반복 가능. `--page-ids` / `--subtree` 와 상호 배타.
- `--since` / `--until` : `YYYY-MM-DD`(UTC 자정으로 정규화) 또는 ISO 8601.
  미지정 시 each = `1970-01-01` / `now()`.
- `--token-budget` : BackfillJob run-level budget. 미지정 시 환경 default.
  per-org 월 ceiling 은 별도 정책 (§6.4) 으로 백본이 강제.
- `--since` / `--until` 의 의미 = `source_updated_at` (= `page.version.when`,
  D6). "처음 만들어진 시점 기준"은 어댑터 옵션 미지원 (Q-CF-7 해결).
- `--dry-run` : §8 출력만, DB write 0.
- `--reingest` : 이미 적재된 page도 다시 처리 (§6.3). 기본 false.
- `--resume <cursor>` : 직전 partial run의 `JobReport.cursor` (D2) 로
  이어서 처리. since/until 과 함께 사용 시 cursor가 우선.

`breadmind kb backfill` (어댑터 미지정) 은 사용 가능한 어댑터 리스트만 출력.

---

## 8. Dry-run 출력 예시

```
$ breadmind kb backfill confluence --org pilot-alpha \
    --space ENG --since 2025-01-01 --dry-run

BackfillJob[confluence] org=pilot-alpha (uuid=8f3...c1)
  source_filter: space=[ENG]  since=2025-01-01  until=2026-04-26
  budget:        token=1,000,000  pages/h=1,000  dry_run=ON

Discover ............ 1,247 pages
Filter ..............   963 keep   /   284 skip   (skipped keys: D1)
  ├── archived ........  18
  ├── draft ...........  62
  ├── empty_page ......  41
  ├── attachment_only .  19
  ├── acl_lock ........ 134   (no active member intersects page ACL)
  ├── restricted ......  20   (kept w/ visibility tag)
  └── already_ingested.  10
Redact ..............   963 pages   (12,471 PII tokens masked)
Embed (estimated) ...   963 pages × ~3 chunks = 2,889 vectors
Store (DRY-RUN) .....     0 rows inserted
Token budget ........   ~412,800 / 1,000,000 (41%)

Sample skips:
  archived  : 11923 "Old onboarding guide (Q3 2022)"
  acl_lock  : 28811 "Compensation review 2025"  (visible to: comp-team)
  empty_page: 31402 "TBD"

Run again without --dry-run to commit. JobReport id: bk-confluence-3a91.
```

(텍스트 형식은 Sub-project 1 합의에 맞춰 정렬된 표면. 컬럼 추가/제거는
공통 spec이 우선.)

---

## 9. 테스트 전략

기존 `tests/kb/connectors/test_confluence.py` 는 incremental 경로 (auth /
TLS / pagination / retry / cassette replay)에 집중되어 있고 **모두 유지**.
backfill 추가는 **새 파일** `tests/kb/connectors/test_confluence_backfill.py`
에 격리:

| 테스트 | 목적 |
|---|---|
| `test_cql_query_built_for_space_filter` | source_filter=space → 올바른 CQL string (D4: server-side `lastModified` 범위) |
| `test_cql_query_for_subtree` | `ancestor=` CQL |
| `test_archived_space_skipped` | discover 단계 skip + reason (D1 키 `"archived"`) |
| `test_acl_lock_drop_when_no_active_member` | §5 drop 경로 + D1 `"acl_lock"` 카운터 |
| `test_restricted_keep_when_member_intersects` | §5 keep + visibility tag |
| `test_active_members_snapshot_taken_at_discover_start` | C1 — discover 직전 1회 스냅샷, run 동안 mutate 안 함 |
| `test_backfill_item_carries_parent_ref_and_timestamps` | D3 + D6 — `parent_ref` + 두 timestamp 매핑 |
| `test_hourly_budget_keyed_by_instance` | D5 — cloud + on-prem 동시 backfill 시 instance별 독립 budget |
| `test_already_ingested_skipped` | 중복 멱등성 |
| `test_reingest_flag_overrides_dedup` | `--reingest` 동작 |
| `test_dry_run_does_not_call_review_queue` | DB write 0 |
| `test_job_report_shape_matches_backbone` | D1 (`skipped: dict[str, int]`) + D2 (`cursor: str \| None`) 스키마 |
| `test_token_budget_terminates_gracefully` | partial JobReport, `cursor` 채워짐 (D2) |
| `test_resume_from_cursor_skips_already_done` | `--resume <cursor>` 동작 |
| `test_org_monthly_ceiling_terminates_run` | per-org 월 token ceiling 강제 |
| `test_incremental_path_unaffected` | **회귀** — 기존 `_do_sync` cursor 동작 동일 (C2: 신규 클래스 분리 검증) |
| `test_source_meta_extracted_from_backfill` | `confluence_backfill` 라벨 |

VCR cassette는 **새 fixture**(`tests/kb/connectors/cassettes/
confluence_backfill_*.yaml`) 로 분리. 기존 cassette는 incremental 전용으로
유지해 record/replay 경계가 흐려지지 않도록 한다.

---

## 10. Open Questions

### 10.1 해결됨 (백본 spec 결정으로 결착)

| ID | 결론 |
|---|---|
| ~~Q-CF-1~~ | **해결 (C2)**: `ConfluenceBackfillAdapter` **신규 클래스**로 통일. 기존 `ConfluenceConnector` (incremental) 와 분리. §6.2 / §3 / §9 의 모든 코드 예시에서 통일. |
| ~~Q-CF-7~~ | **해결 (D6)**: `source_created_at` (= `page.history.createdDate`) 와 `source_updated_at` (= `page.version.when`) **둘 다 보존**. CLI `--since/--until` 의 의미는 `source_updated_at` 기준 (incremental 과 일관). 추가 플래그 필요 시 별도 RFC. |

### 10.2 남은 Open Questions

| ID | 질문 | 충돌 / 미정 사유 |
|---|---|---|
| Q-CF-2 | `org_knowledge` 에 visibility 정식 컬럼 추가? (`source_channel` 우회는 임시) | 별도 마이그레이션 spec 필요. 본 spec은 §5에서 임시로 channel suffix 사용 |
| Q-CF-3 | body view 포맷 도입 (macro 렌더 결과 보존) | 매크로 결과의 시점 의존성 vs 검색 품질 트레이드오프. **본 spec 권장: storage 유지** (§3.1) — 추후 view 도입은 별도 RFC |
| Q-CF-4 | `--reingest` 시 기존 row를 `superseded_by` 로 체이닝 vs in-place update | retirement scan 정책과의 일관성 검토 필요 |
| Q-CF-5 | 활성 멤버 집합 `M` 의 결정 규칙 (org_projects member 테이블 ↔ Slack workspace member 매핑) | org_id Phase 2 v2 carry-over. C1 의 스냅샷 시점은 결정됨; 어떤 테이블에서 멤버를 확정할지는 미해결 |
| Q-CF-6 | CQL endpoint 권한이 `Basic email:api_token` 으로 충분한가, 아니면 OAuth scope 추가 필요한가 | Atlassian Cloud 기준 `read:confluence-content.summary` 만으로 가능; on-prem Server는 별도 검증 |
| Q-CF-8 | Backfill 도중 incremental scheduler가 같은 space에 도는 경우 락? | `connector_sync_state` 는 backfill이 안 건드리므로 데드락 없음, 다만 동일 페이지 중복 적재는 §6.3 dedup으로 해결 — 충돌 가능성 낮지만 명시 필요 |

---

## 11. Non-Goals

- `_do_sync` 시그니처 변경 / cursor 의미 변경 — **불가**.
- Confluence 외 다른 connector(Notion / Drive 등) 의 backfill — Sub-project
  4 이후.
- attachment(PDF/DOCX) ingest — 본 spec에서는 attachment-only를 skip.
- 과거 시점 ACL 재현 — 합의대로 "현재 기준" 만.

---

## 12. Risks

| Risk | 영향 | 완화 |
|---|---|---|
| CQL endpoint가 spaceKey-only endpoint와 다른 권한 정책 | discover 0 페이지로 조용히 끝남 | smoke test에서 1 페이지 fetch dry-run을 자동 수행 |
| `restrictions.read` expand 가 응답을 무겁게 함 | rate-limit 조기 hit | `_PAGE_LIMIT` 25로 자동 하향 (heuristic, post-MVP) |
| dedup 쿼리(`kb_sources` lookup) 가 N+1 | 대규모 backfill 시 DB 부하 | discover 직후 단일 IN-list 조회로 prefetch (구현 디테일) |
| `created_at` 가 source값으로 채워지면 기존 retriever recency 가중치 왜곡 (D6: source-side timestamp 보존) | KB 검색 품질 회귀 | rank_weight 결정 단계에서 backfill 행을 `source_updated_at` 기준 normalize (Sub-project 1 책임) |
| **incremental ↔ backfill 클래스 분리 (C2)** 가 부족하게 documented 되어 후속 개발자가 `ConfluenceConnector` 에 backfill 메서드를 추가해버림 | C2 위반 → incremental 회귀 | `confluence.py` 모듈 docstring + adapter 모듈에 명시; `test_incremental_path_unaffected` 로 회귀 가드 |

---

## 13. Out-of-spec Notes

- 본 spec은 `confluence.py` 외 파일을 변경하지 않는 가정으로 작성. 단, CLI
  엔트리포인트는 `src/breadmind/cli/` 또는 `src/breadmind/main.py` 에 신규
  서브커맨드를 등록해야 하는데, 이는 Sub-project 1의 `breadmind kb backfill`
  공통 dispatcher 가 어댑터를 plug-in 형태로 받는 구조라면 connector 쪽에
  코드 변경이 거의 없게 된다. 해당 dispatcher 디자인 = Sub-project 1.
- `_E2EConfluenceFacade` / `build_for_e2e` / `build_for_tests` 는 **건드리지
  않는다**. backfill 테스트는 별도 facade 가 필요하면 신규로 추가.
