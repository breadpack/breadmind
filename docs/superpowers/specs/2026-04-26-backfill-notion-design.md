# Notion Org Connector + Backfill Adapter Design

**작성일:** 2026-04-26
**상태:** Draft v2 (Sub-project 2 of "공통 Backfill 파이프라인" 시리즈) — 백본 결정 D1~D6 / C1~C2 반영
**선행/병행:**
- Sub-project 1 (백본) — 공통 `BackfillJob` 인터페이스 / `JobReport` / 단계 파이프라인 (`discover → filter → redact → embed → store`) / `dry_run` semantics **단일 출처 확정**.
- 본 spec은 그 인터페이스를 **그대로 가정**하고 위에 Notion 어댑터를 얹는다.
**Reference 패턴:** `src/breadmind/kb/connectors/confluence.py` (조직용 connector), `src/breadmind/kb/connectors/base.py` (`BaseConnector` 추상).
**개인용 비교 대상:** `src/breadmind/personal/adapters/notion.py` (Task DB sync 전용, 본 spec은 페이지 KB ingest 전용 — 분리).

### 백본 spec과의 인터페이스 계약 (단일 출처)

본 어댑터가 **그대로 따르는** Sub-project 1 결정:

- **D1. `JobReport.skipped: dict[str, int]`** — 사유별 카운터. Notion-특화 키는 §4 표 참조 (`empty_page`, `template`, `archived`, `in_trash`, `acl_lock`, `redact_dropped`, `share_revoked`, `duplicate_body`, `title_only`, `oversized`).
- **D2. `JobReport.cursor: str | None`** — opaque token. 어댑터의 `cursor_of(item) -> str` 인코딩 책임. 본 어댑터는 `last_edited_time:page_id` 형태 사용 (§6.1).
- **D3. `BackfillItem.parent_ref: str | None`** — 부모 row 참조. Notion subpage가 부모 페이지를 가리킬 때 채움 (§3 매핑).
- **D4. `since/until` 필터는 어댑터 책임** — Notion search API가 server-side timestamp range 필터를 미지원하므로 어댑터가 sort 후 client-side cut으로 since/until 범위 안에서만 yield.
- **D5. `HourlyPageBudget` instance-keyed 차원** — Notion에서 `instance_id`는 workspace_id. 어댑터의 `instance_id_of(source_filter) -> workspace_id` 한 줄로 매핑 (§5.2).
- **D6. timestamp 2개 매핑** — `source_created_at` ← Notion `created_time`, `source_updated_at` ← Notion `last_edited_time`. 둘 다 `kb_sources`에 저장.

Cross-cutting:

- **C1. 권한 락 시점** — `discover()` 시작 직전 활성 멤버 셋 스냅샷 + per-item ACL은 표시만. **단 Notion 권한 모델은 share-in 단위라 활성 멤버 비교가 직접 적용 불가** — 본 spec에서는 백필 범위를 "운영자가 사전에 share-in한 root 페이지 트리의 union"으로 정의 (§2.3). share-in 풀린 페이지의 mid-run 404는 정상 경로 (`skipped["share_revoked"]`).
- **C2. 어댑터 클래스 명명** — 신규 `NotionBackfillAdapter` 클래스. `personal/adapters/notion.py`(개인용)와 분리 결정 유지 (§9).

---

## 1. Overview — 무엇을 indexing 할 것인가

조직 Notion workspace를 BreadMind `org_knowledge` KB로 1회성/증분 백필한다. 우선순위:

| 우선 | 항목 | 처리 방식 |
|---|---|---|
| **P0** | Top-level pages + 중첩 페이지 (block tree 평탄화) | 1 page → 1 candidate (블록 트리 → markdown) |
| **P0** | 페이지 본문 안의 텍스트/heading/list/quote/code 블록 | inline 평탄화 |
| **P1** | Database — 각 row 페이지 (`databases.query`) | 페이지와 동일 처리. DB 자체의 schema/description은 1개의 "DB 인덱스 페이지"로 단일화 |
| **P1** | 페이지의 `child_database` 블록 — 상위 페이지에서 보이는 inline DB | row를 별도 페이지로 분리해서 처리 |
| **P2** | Comments (`/v1/comments?block_id=`) | Phase 2로 미룸. 빈 페이지에 코멘트만 있는 케이스 위해 P2에서 추가. |
| **P3** | 첨부파일 / 이미지 / file 블록 | **본 Phase 미포함.** 본문에는 placeholder text(`[file: <name>]`)만 남김. Phase 3에서 OCR/추출 별도 spec. |
| 제외 | 휴지통 / archived / template / 빈 페이지 / 너무 짧은 페이지 | §4 Signal Filter에서 drop |

각 page는 `org_knowledge` 1행 + `kb_sources` 1행으로 매핑된다 (Confluence와 동일 모델 — §3 참조).

---

## 2. 인증 / 권한 모델

### 2.1 Integration 종류

Notion은 두 종류 integration이 있고 본 connector는 **Internal Integration** 만 지원한다 (Phase 2 spec):

| 타입 | 본 spec | 사유 |
|---|---|---|
| Internal Integration (workspace-bound, single token) | **지원** | 온프레 BreadMind에 적합. workspace owner가 token 1개 발급 → vault 보관. |
| Public Integration (OAuth 3-legged) | **미지원 (Phase 3 후속)** | OAuth redirect, refresh token rotation, multi-workspace 라우팅 필요 — Sub-project 1 정착 후 별도 spec. |

### 2.2 Token 보관

- `CredentialVault`에 `notion:org:<project_id>` 키로 raw token 1개 저장.
- Confluence와 달리 `email:token` 형태 아님 — Notion은 `Authorization: Bearer secret_xxx` + `Notion-Version: 2022-06-28` 헤더 1쌍.
- `personal/adapters/notion.py`의 헤더 빌더와 형태는 같으나, 인증 키 lookup 경로가 다르므로 코드 공유 X (§9 참조).

### 2.3 Page Access 권한 (Notion 특화 제약 — C1 적용)

**Notion의 권한 모델은 사용자가 통합을 명시적으로 페이지/DB에 "추가" 해야만 API가 그 페이지를 본다.** Confluence space 단위 권한과 본질적으로 다르고, 백본 spec C1의 "활성 멤버 스냅샷"이 직접 적용 불가능:

- Workspace 레벨에서 token이 유효해도, integration이 "Add connections"로 명시적으로 share 안 된 페이지는 `search` 결과에 안 나오고 직접 fetch 시 404.
- **결과 (백본 C1을 Notion 모델로 해석):** 백필 범위 = "운영자가 사전에 share-in한 root 페이지 트리의 union". 운영자가 root-level 페이지에 통합을 추가하면 자손은 inherit. 활성 멤버 셋 스냅샷 대신 **"discover 시작 직전의 share-in 페이지 셋"** 을 락 시점으로 사용.
- per-item ACL은 표시만 (백본 C1 후반부와 동일) — 페이지마다 별도 권한 비교 없음.
- 권한 락 시점: `discover()` 시작 직전 1회 스냅샷. discover/store 사이에 share-in이 풀려 mid-run 404가 발생하는 페이지는 **정상 경로**로 다룸 → `JobReport.skipped["share_revoked"]` 카운터 + audit log 1줄. 다음 incremental sync에서 자연 정리.

---

## 3. 데이터 매핑

### 3.0 `BackfillItem` 채움 규약 (백본 D3 / D6 정렬)

백본 `BackfillItem` 인터페이스를 어댑터가 채울 때 Notion-source 매핑:

| `BackfillItem` 필드 | Notion source | 비고 |
|---|---|---|
| `source_id` | page id (UUID without dashes) | `kb_sources.source_ref`와 동일 |
| `source_created_at` | `page["created_time"]` (ISO 8601) | **D6** |
| `source_updated_at` | `page["last_edited_time"]` (ISO 8601) | **D6**, cursor 인코딩에도 사용 |
| `parent_ref` | 부모 page id (subpage이면) / 부모 DB id (DB row이면) / `None` (root) | **D3**. block의 `parent.type` ∈ {`page_id`, `database_id`, `workspace`} 분기. workspace인 경우 `None`. |
| `instance_id` | workspace_id | **D5**, `HourlyPageBudget` 차원 |
| `title` | §3.1 매핑 | |
| `body` | block tree → markdown (§3.2) | |
| `estimated_tokens` | tiktoken 추정치 | dry-run에서 합산 |

**`parent_ref` 사용 예시:**

- subpage `XYZ`가 root page `ABC` 아래에 있으면 → `BackfillItem(source_id="XYZ", parent_ref="ABC", ...)`.
- DB `D1`의 row `R1` → `BackfillItem(source_id="R1", parent_ref="D1", ...)`.
- root page (workspace 직속) → `parent_ref=None`.
- 백본 파이프라인은 `parent_ref`를 사용해 향후 hierarchical chunking / context anchor를 구성할 수 있음 (본 어댑터는 채우는 책임만).

### 3.1 Notion page → `org_knowledge` row (Confluence와 동일 스키마)

| `org_knowledge` 컬럼 | Notion source |
|---|---|
| `project_id` | CLI / connector config의 `--org` (UUID, `org_projects.id`) |
| `title` | page `properties["title"]` plain_text concat (DB row면 `Name`/`Title`) |
| `body` | block tree → markdown (§3.2) |
| `category` | extractor가 결정 (`howto`/`decision`/...). connector는 후보만 enqueue, 최종 분류는 `KnowledgeExtractor`. |
| `body_embedding` | embed pipeline이 채움 (Sub-project 1) |
| `superseded_by` | NULL (신규) |

`kb_sources` 행:

| 컬럼 | 값 |
|---|---|
| `source_type` | `'notion'` |
| `source_uri` | `https://www.notion.so/<workspace>/<page-slug-id>` (page 객체의 `url` 그대로) |
| `source_ref` | Notion page id (UUID without dashes — Notion canonical 형태) |
| `original_user` | page `created_by.id` (Notion user id) |
| `extracted_from` | `'notion_backfill'` (또는 incremental run이면 `'notion_sync'`) |
| `captured_at` | `now()` |
| `source_created_at` | `page["created_time"]` (ISO 8601) — **D6** |
| `source_updated_at` | `page["last_edited_time"]` (ISO 8601) — **D6**, cursor 인코딩 입력 |
| `parent_ref` | 부모 page/DB id (있으면) — **D3** |

### 3.2 Block Tree → Text 평탄화

Notion은 페이지 본문을 **블록 트리**로 표현하고 children을 별도 호출(`blocks.children.list`)로 가져와야 한다. 평탄화 규칙:

| 블록 타입 | 변환 |
|---|---|
| `paragraph`, `quote`, `callout` | rich_text plain → 단락 (`\n\n`) |
| `heading_1/2/3` | ATX `#`/`##`/`###` |
| `bulleted_list_item`, `numbered_list_item`, `to_do` | `- ` / `1. ` / `- [x] ` (체크박스는 상태 보존) |
| `code` | fenced ``` ` ``` block + language |
| `toggle` | summary line + 들여쓴 children |
| `table`, `table_row` | GitHub pipe table |
| `child_page` | **별도 page로 큐잉** (재귀 X — discover 단계가 list로 이미 잡음) |
| `child_database` | DB id를 별도 discover entry로 큐잉 |
| `image`, `file`, `pdf`, `video`, `audio`, `bookmark` | placeholder text (`[file: <caption_or_name>]`) — P3 후속 |
| `equation` | `$$<expr>$$` |
| `divider`, `breadcrumb`, `table_of_contents` | drop (스킵) |
| `synced_block` | **원본만** 한 번 평탄화. mirror는 본문 X, sources_json에 cross-ref만. |
| `column_list`, `column` | flatten (단순 concat — column 정보 손실 OK) |

children depth는 **최대 8단까지만** 따라간다 (재귀 폭주 방지). 더 깊은 페이지는 truncation marker 한 줄 + 후속 incremental에서 다시 시도.

### 3.3 Database 처리

DB 자체와 row를 분리:

- DB 메타 (title, description) → 1개의 인덱스 페이지로 indexing (검색 시 "이 DB가 무엇인지" 답하기 위해).
- 각 row → 일반 page와 동일하게 처리. `databases.query`로 페이지네이션, `properties`는 §3.1 title 매핑 + 본문은 row의 child block list.

---

## 4. 시그널 필터 (Notion 특화) — D1 `JobReport.skipped` 키 매핑

`discover()` 직후 / `redact` 전 단계에서 다음 조건 중 하나라도 hit 시 drop. 각 룰은 **백본 D1 `JobReport.skipped: dict[str, int]` 카운터의 Notion-특화 키**로 누적:

| 룰 | 임계 | `skipped` 키 | 사유 |
|---|---|---|---|
| `archived == true` | 페이지 객체의 `archived` 플래그 | `archived` | Notion의 휴지통 — 절대 indexing X |
| `in_trash == true` | API에서 노출되는 휴지통 플래그 | `in_trash` | 동상 |
| Template 페이지 | 부모가 `template:true` 이거나 title prefix `Template:` (heuristic) | `template` | 빈 placeholder 본문이 KB 오염 |
| 빈 페이지 | 평탄화 후 markdown body 길이 < **120 chars** (whitespace 제외) | `empty_page` | 의미 없는 stub |
| Title-only 페이지 | block 0개 + title만 있는 케이스 | `title_only` | 대부분 navigation index |
| 너무 큰 페이지 | markdown > **200,000 chars** | `oversized` | 1 page로 들어가지 않게 chunking이 처리하지만, 비정상 dump 신호로 1 page는 split + audit log 1줄 |
| Duplicate 본문 | 같은 project 내 `(title, body_hash)` 충돌 | `duplicate_body` | 동일 페이지 중복 import 방지 (Notion duplicate 기능 흔함) |
| Share-in 풀린 페이지 (mid-run 404) | discover 후 fetch 시 404 | `share_revoked` | C1 — 정상 경로 |
| ACL lock 시점에 안 보이는 페이지 | discover 직전 share-in 셋 밖 (Notion search가 반환 안 함) | `acl_lock` | C1 — Notion 모델 특성상 보통 0, 백본 dashboard 호환 위해 키만 유지 |
| Redactor가 전체 drop | 본문 전체가 PII/secret로 가려져 의미 없음 | `redact_dropped` | Sub-project 1 redact 단계 산출 |

추가로 §1의 P3 (file/attachment) 페이지는 본문이 placeholder만이면 자동으로 `empty_page` 조건에 걸려 drop — 의도된 동작.

위 키 외 어댑터가 임의 추가하지 않는다 — 백본 dashboard가 union dictionary로 표시하므로 키 폭발 방지. 신규 사유가 필요하면 백본 spec PR 우선.

**룰 평가 순서 (중첩 시 첫 번째 일치만 카운트):**
`archived` → `in_trash` → `template` → `acl_lock` → `share_revoked` → `title_only` → `empty_page` → `oversized` → `duplicate_body` → `redact_dropped`. (예: title-only는 `empty_page`보다 먼저 평가되어 별도 카운터로 누적.)

---

## 5. Rate Limit 전략

Notion 공식 API 한도: **average 3 requests / second per integration** (Notion API docs / `429` with `Retry-After` 헤더).

### 5.1 토큰 버킷

connector 내부에 `asyncio.Semaphore(1)` + `asyncio.sleep` 기반 **3 rps 토큰 버킷**:

```
acquire → if since_last < 333ms: sleep(333ms - delta)
```

- 동시성 제한: 1 (Notion이 burst를 좋아하지 않음 — Confluence보다 보수적).
- 재시도: 429 → `Retry-After` 헤더 우선. 없으면 backoff `(60s, 300s, 1800s)` (Confluence와 동일 순서).
- 5xx → 동일 backoff.

### 5.2 `HourlyPageBudget` 통합 (D5 instance-keyed 차원)

`connectors/rate_limit.py`의 `HourlyPageBudget`을 **백본 D5의 instance-keyed 차원**으로 사용:

- `instance_id_of(source_filter) -> workspace_id` — Notion 어댑터에서 `instance_id`는 workspace_id (한 org가 여러 workspace를 share-in한 경우 분리 카운트).
- `consume(project_id, instance_id=workspace_id)` 매 page마다 호출.
- limit 초과 시 `BudgetExceeded` → backfill을 멈추고 cursor (D2: `last_edited_time:page_id`) 보존 후 종료 (Confluence와 동일 패턴).

### 5.3 `token_budget` (Sub-project 1 입력) + per-org 월 ceiling

- `BackfillJob.token_budget`은 LLM 입력 토큰 예산이고, dry-run에서 `estimated_tokens` 미리 합산.
- **per-org 월 token ceiling (백본 P1 신규)** — 백본이 도입한 ceiling이 본 어댑터에도 적용. `BackfillJob.token_budget`은 단일 run 한도, ceiling은 org 누적 한도.
- **초과 시 정책 (백본 P4 일관성: fail-closed)** — 어댑터는 자동 trim 안 함. dry-run에서 ceiling/budget 초과 감지 시 텍스트로 안내 후 **종료 코드 2 (budget exceeded)** 반환. 운영자가 `--since` 좁혀서 재실행하는 게 1차 UX. ingest mode에서 ceiling이 run 중 초과되면 마지막 안전 cursor 보존 후 fail-closed 종료.

---

## 6. Backfill 흐름

`BaseConnector` + `BackfillJob` (Sub-project 1) 둘 다 만족하는 형태.

### 6.1 `discover()`

두 가지 경로 중 **Search-based (Phase 2 default)**:

| 방식 | 장점 | 단점 |
|---|---|---|
| `POST /v1/search` (filter `object: page`, `sort.timestamp=last_edited_time desc`) | 단순. Notion이 권한 인지해서 보이는 페이지만 반환 | search index lag (수 분), `filter` 표현력 약함 — 빈/template 필터링 불가 → §4 client-side |
| Sitemap-style (root page 트리 walk via `blocks.children.list` recursion) | 정확 | 매우 느림, root list를 사전에 알아야 함 |

→ **Search 1차, sitemap fallback은 Phase 3 후속.**

증분 paging — **백본 D2 (opaque cursor) + D4 (어댑터 책임 client-side cut) 적용**:

- **D2.** 영속 cursor 형식 = `f"{last_edited_time_iso}:{page_id}"` (백본 입장에서는 opaque string, 어댑터 내부에서만 파싱). page_id 동률 tiebreak 포함해 안정 정렬 보장.
- **D2.** 어댑터의 `cursor_of(item: BackfillItem) -> str` 구현이 위 형식 인코딩 책임 — 백본은 모름.
- **D4.** Notion search API는 server-side timestamp range를 미지원 (`sort` only) → 어댑터가 `last_edited_time desc` 정렬 후 **client-side cut**으로 `[since, until)` 범위 안에서만 yield.
- search response가 cursor 구분점보다 오래된 첫 페이지를 반환하면 search pagination 중단.
- search 내부 페이지네이션의 `next_cursor`는 in-memory only — 영속 저장 안 함 (D2 cursor와 분리).

### 6.2 단계 (Sub-project 1 파이프라인 위)

```
discover()         → Notion search + DB enumeration + client-side since/until cut (D4)
                  → list[BackfillItem]  (parent_ref/source_created_at/source_updated_at 채움 — D3/D6)
filter(signal)     → §4 룰 적용 → JobReport.skipped[<key>]++ (D1)
                  ↓ pass:
fetch_blocks()     → blocks.children.list (재귀, 최대 depth 8)
flatten()          → markdown text (§3.2)
redact()           → kb/redactor.py (PII/secret) — Sub-project 1 단계
embed()            → Sub-project 1
store()            → org_knowledge + kb_sources upsert (`source_ref` UNIQUE)
                     cursor_of(item) → connector_sync_state.last_cursor (D2)
```

### 6.3 Idempotency

- `kb_sources (source_type, source_ref)` UNIQUE.
- 같은 page id 재발견 시 → `org_knowledge.body_hash` 비교 → 동일하면 no-op, 다르면 새 row + 이전을 `superseded_by` 로 link (Confluence retirement 패턴 동일).
- `dry_run=true` 일 땐 store 단계 skip, 모든 카운터만 누적.

### 6.4 Failure Isolation

페이지 단위 try/except — 1 page 실패가 전체 백필을 중단시키지 않음. `JobReport.errors`에 `(page_id, reason)` append.

---

## 7. Dry-run 출력 예시

CLI 텍스트 1차 (Sub-project 1 합의). 운영자가 `--dry-run`으로 가장 먼저 보는 화면:

```
$ breadmind kb backfill notion --org 7c1a5b94-... --workspace pilot-alpha \
    --since 2026-01-01 --dry-run

[notion-backfill] org=7c1a5b94 workspace=pilot-alpha since=2026-01-01 until=now
[notion-backfill] discover via Notion search ...

  discovered pages          : 1,284
  in scope after filter     :   932
    skipped[archived]       :    71
    skipped[template]       :    18
    skipped[empty_page]     :   201
    skipped[in_trash]       :     5
    skipped[duplicate_body] :    57
  inline databases          :    14  (rows queued: 312)

  estimated tokens (input)  : 1.84M  (run budget=2.00M, org month ceiling=18.4M of 20M)  [OK]
  estimated chunks          : 4,127
  estimated embed cost      : ~$2.06 (text-embedding-3-small @ $0.02/M)
  estimated wall-clock      : ~58 min @ 3 rps

  rate limit                : 3 rps, hourly budget 1000 pages (instance=workspace pilot-alpha)
  redact policy             : kb/redactor.py default (vocab=org-pilot-alpha)

  permission lock            : share-in snapshot @ discover start (C1)
                              (1,284 pages visible to integration; mid-run 404 → skipped[share_revoked])
  cursor format              : last_edited_time:page_id (D2, opaque to backbone)

[notion-backfill] DRY RUN — no rows written. Re-run without --dry-run to ingest.
```

이 텍스트는 사용자 검토용이므로 "drop 사유별 카운트"를 반드시 포함 (Sub-project 1 `JobReport.skipped` 분해).

---

## 8. CLI Entry Point

```
breadmind kb backfill notion \
    --org <project_uuid> \
    --workspace <workspace_label> \
    [--since YYYY-MM-DD] [--until YYYY-MM-DD] \
    [--token-budget 2000000] \
    [--dry-run]
```

- `--org`: `org_projects.id` UUID (Sub-project `org_id` Phase 2 v2와 일관).
- `--workspace`: 사람 친화 라벨. 내부적으로는 `connector_configs.scope_key = "notion:<workspace>"`로 매핑 — 한 org가 여러 Notion workspace를 쓸 수 있는 미래 대비.
- `--since` / `--until` 미지정 시: `since = last_cursor or 1970-01-01`, `until = now`.
- `--dry-run` 미지정 = ingest mode (실제 store).
- 출력은 §7과 동일한 라인 + 진행 막대(`tqdm`은 옵션). 종료 코드: `0` 정상, `2` budget exceeded, `3` auth fail, `1` 기타.

내부적으로 `BackfillJob` (Sub-project 1)을 인스턴스화하고 `NotionBackfillAdapter` (C2)를 source로 등록. `BackfillJob.run()` 호출 → `JobReport` 반환 (skipped 카운터는 D1 키 셋) → 위 텍스트로 렌더.

---

## 9. `personal/adapters/notion.py`와의 공유 vs 분리 (C2)

**결정 (백본 C2): 분리.** 신규 클래스명 = **`NotionBackfillAdapter`** (`kb/connectors/notion.py` 또는 `kb/connectors/notion_backfill.py`). 본 spec 전체에서 어댑터 명명을 통일. 다음 근거.

| 항목 | personal | org connector (본 spec) |
|---|---|---|
| 목적 | Task DB 양방향 sync (CRUD) | Read-only KB ingest (page tree → markdown) |
| 매핑 대상 | DB row → `Task` dataclass | Page tree → `org_knowledge` + `kb_sources` |
| 인증 lookup | `credentials.api_key` (직접 dict) | `CredentialVault.retrieve("notion:org:<id>")` |
| 권한 모델 | personal token, 단일 DB | integration share-in 트리 (page-level) |
| 호출 표면 | `list_items / create_item / update_item / delete_item / sync` | `BackfillJob` 단계 (`discover/filter/...`) |
| 베이스 클래스 | `personal.adapters.base.ServiceAdapter` | `kb.connectors.base.BaseConnector` |
| Block fetch | 안 함 (DB row만) | 핵심 (`blocks.children.list` 재귀) |
| 외부 의존 | aiohttp 직접 | aiohttp + 공통 redactor / quota / rate_limit |

**공유 가능한 좁은 부분 — 별도 모듈로 추출 후 양쪽에서 import:**

- `_BASE_URL = "https://api.notion.com/v1"` 상수.
- `_NOTION_VERSION = "2022-06-28"` 상수.
- `_parse_iso(value)` — Notion ISO 8601 (`Z` → `+00:00`) 파서.
- 저수준 헤더 빌더 helper (`_headers(api_key)`).

→ 위 4개를 `src/breadmind/integrations/notion_common.py` (혹은 `kb/connectors/notion_common.py`) 신규 파일로 분리. `personal/adapters/notion.py`는 후속 작은 PR에서 그쪽으로 import 변경 (본 spec 범위 외이지만 흐름은 명시).

**공유하지 않는 이유 (의도적 분리):**

- 클라이언트 본체 (HTTP 세션 / 재시도 / pagination) 로직이 양쪽에서 너무 다르게 발달함. personal의 `_request`는 단순 raise_for_status, org는 backoff + 429 retry-after + rate-limit semaphore. 합치면 분기로 누덕누덕해짐.
- `NotionAdapter` (personal)는 task domain (status/priority/due_at 매핑)에 강하게 결합돼 있어 KB ingest 경로에는 짐. `NotionBackfillAdapter`는 read-only page ingest 단일 책임.
- `personal`은 사용자별 token, `org`는 project별 token + vault lookup — 인증 표면이 다른 클래스로 표현되는 게 옳음.

---

## 10. 테스트 전략

| 레벨 | 케이스 | 데이터 |
|---|---|---|
| Unit | `_flatten_blocks` — 모든 §3.2 블록 타입 round-trip | 정적 fixture JSON |
| Unit | Signal filter — archived/template/short/duplicate 각 1 | inline dict |
| Unit | Rate limit — 3 rps 토큰 버킷 (mock `time.monotonic`) | 단순 |
| Unit | Pagination cursor — search response 2페이지 + `since` 컷 | recorded fixture |
| Unit | 권한 변경 시뮬레이션 — discover 중 페이지 404 | mock session |
| Integration | testcontainers Postgres + recorded Notion fixture → org_knowledge insert + kb_sources insert + last_cursor 진행 | `tests/kb/connectors/notion_fixtures/` |
| Integration | dry-run 결과의 카운터 = 실 ingest 시 기록 수 (±skipped) | 동상 |
| Integration | 재실행 idempotency — 동일 fixture 두 번 → row 동일, body_hash 동일이면 no-op | 동상 |
| E2E (optional) | Confluence처럼 `build_for_e2e` facade — 실 Notion API 안 치고 fixture 기반 | Phase 2 후속 |

목표 coverage: connector 모듈 단독 ≥ 90%. `kb/connectors/confluence.py` 기준선과 동일 수준.

---

## 11. Open Questions

> Sub-project 1 (백본) 결정으로 해결된 항목과 본 어댑터 범위에 남은 항목 분리.

### 11.1 백본 결정으로 해결됨 (참고용 — 더 이상 open 아님)

- ~~**source `created_at` 저장 위치**~~ → **D6 해결.** `source_created_at` + `source_updated_at` 둘 다 `kb_sources` 컬럼으로 저장 (§3.1 / §3.0 표).
- ~~**Cursor 형식**~~ → **D2 해결.** opaque token, 어댑터의 `cursor_of(item)` 책임. 본 어댑터는 `last_edited_time:page_id` 사용 (§6.1).
- ~~**권한 락 시점**~~ → **C1 + Notion 특수 모델로 해결.** discover 시작 직전 share-in 셋 스냅샷, mid-run 404는 `skipped["share_revoked"]` 정상 경로 (§2.3 / §4).
- ~~**Token budget 초과 시 자동 trim vs 사용자 재지정**~~ → **백본 P1 ceiling 도입 + P4 fail-closed 일관성으로 해결.** 자동 trim 안 함, 종료 코드 2 + 안내 (§5.3).

### 11.2 남은 Open Questions (어댑터 범위)

1. **Notion comments Phase 2 포함 여부** — §1 P2. Phase 2의 본 백필에 포함 vs Phase 3로 미룸. 운영자 입장에서 "리뷰/결정 흐름이 코멘트에 남는다"는 의견이 있으면 P2를 Phase 2 내 fast-follow로 승격할 수 있음.
2. **Synced block 정책** — 원본만 indexing하기로 했으나, 운영자가 mirror 위치만 검색에 노출하고 싶을 가능성. 현재안 = 원본 1회 + sources_json에 mirror cross-ref. 사용자 검토 필요.
3. **Public OAuth Phase 3 타이밍** — Phase 2의 Internal-only 결정이 다중 workspace + tenant-isolated SaaS 전환 시 충분한가. 현 BreadMind 온프레 가정에서는 OK. Phase 3 spec 시작 시점 미정.
4. **DB row collapse 옵션** — 한 DB의 모든 row가 의미가 비슷한 경우 (`Q&A` DB, `의사결정 로그` DB 등) row마다 KB 엔트리가 폭발. 현재안 = row마다 분리. opt-in으로 `databases.<db_id>.collapse=true` 설정 시 1개 본문으로 합치는 옵션 — Phase 2.1 후속.
