# Backfill Connector — Redmine (Sub-project 4 Design Spec)

- Date: 2026-04-26
- Status: Draft v2 (aligned with Sub-project 1 backbone decisions D1–D6, C1–C2)
- Scope: Design only. Implementation lands after Sub-project 1 (`BackfillJob` pipeline) is merged.
- Reference connector: `src/breadmind/kb/connectors/confluence.py`
- Adapter class (canonical): **`RedmineBackfillAdapter`** (per backbone decision C2).

## Overview

Add a first-class **Redmine** connector to the BreadMind KB ingestion pipeline. Unlike Slack (chat) or Confluence (wiki) which already exist, Redmine is the first **issue-tracker-style** source we onboard via the new common `BackfillJob` pipeline produced by Sub-project 1. The goal is to import historical institutional knowledge buried in resolved tickets, post-mortem journals, and wiki/runbook pages — without re-importing transient noise (status churn, auto-bot comments).

### Indexing targets, in priority order

| Priority | Object                              | Why                                                                |
|---------:|-------------------------------------|--------------------------------------------------------------------|
| P0       | **Issue** (subject + description)   | Stable problem statement; canonical "what we knew at the time."    |
| P0       | **Journal notes** (human comments)  | The actual debugging / decision narrative. Highest signal density. |
| P1       | **Wiki page**                       | Curated runbooks; shape similar to Confluence pages.               |
| P2       | **Attachments** (text/markdown/log) | Only when MIME is text-like and size ≤ 1 MB.                       |
| Out      | Time entries, news, forums, files   | No KB value for v1.                                                |

The connector emits the same `(SourceMeta, body)` tuples the common pipeline expects, so redaction / embedding / pgvector storage is unchanged.

## Backbone Contract Alignment (Sub-project 1)

This adapter implements the common `BackfillAdapter` interface. The following decisions from the Sub-project 1 backbone are **binding** for every code/CLI/dry-run example below:

- **D1 — `JobReport.skipped: dict[str, int]`**: per-reason counters. Redmine-specific keys this adapter increments: `"private_notes"`, `"metadata_only_journal"`, `"empty_description"` (a.k.a. `min_description_chars`), `"closed_old"` (closed-only filter), `"acl_lock"`, `"auto_generated"` (bot authors). The dry-run report below maps 1:1 onto these keys.
- **D2 — `JobReport.cursor: str | None`** (opaque). The pipeline does not parse it. This adapter implements `cursor_of(item) -> str` as `f"{updated_on.isoformat()}:{issue_id}"`. The pagination concern previously listed under "structured cursor" is therefore resolved by adapter-side encoding only — the pipeline contract stays a single string.
- **D3 — `BackfillItem.parent_ref: str | None`** is now a first-class field. Redmine journal rows set `parent_ref = f"redmine_issue:{issue_id}"`; attachment rows set `parent_ref = f"redmine_issue:{issue_id}"` or `f"redmine_wiki:{page_id}"`. Issue anchor rows have `parent_ref = None`. Retrieval may boost children when their parent scores high.
- **D4 — `since`/`until` filtering is the adapter's responsibility**: issues use server-side `updated_on=>=<since>&updated_on=<=<until>` against `/issues.json`; journals are filtered in-memory per issue (Redmine has no per-journal time filter); wiki uses per-page `updated_on` checks after `index.json` enumeration.
- **D5 — `HourlyPageBudget` instance-keyed dimension**: this adapter keys budget on `(org_id, instance_id)` where `instance_id = sha256(base_url)[:16]`. Backwards-compatible with the existing per-`project_id` key (a job that supplies both will be charged on the more restrictive of the two). Resolves the "one org, many Redmine projects, single rate-limited instance" case.
- **D6 — Two timestamps on every `BackfillItem`**:
  - `source_created_at`: issue → `issue.created_on`; journal → `journal.created_on`; wiki → first version's `created_on`; attachment → `attachment.created_on`.
  - `source_updated_at`: issue → `issue.updated_on`; journal → `journal.created_on` (journals are immutable in Redmine, so created==updated); wiki → page `updated_on`; attachment → `attachment.created_on` (Redmine attachments are immutable).
- **C1 — Permission lock at discover-start**: the adapter snapshots active project memberships **immediately before** `discover` begins, via `GET /projects/<id>/memberships.json` (one call per included project). The snapshot is the ACL set used for every row emitted by this job, even if memberships change mid-run. Per-item ACL marker is written on every `BackfillItem` (see "Permission Lock" section below).
- **C2 — Adapter class**: `RedmineBackfillAdapter` (single canonical name; all references in this spec use it).

### Operational policy

- **Per-org monthly token ceiling** (backbone-wide policy): this adapter respects the org's monthly embed-token ceiling published by Sub-project 1; if exceeded mid-job the adapter halts discover early and reports `partial=True` with `cursor` set to the last completed page's encoded position.

## Authentication

Redmine offers three auth modes; **OAuth is not part of Redmine core** (only via 3rd-party plugins, which we cannot assume on-prem).

Decision: support **API key** as the only first-class mode, plus **HTTP Basic** as a fallback for very old on-prem instances that have user-key disabled.

- API key transport: `X-Redmine-API-Key: <key>` header (Redmine ≥1.1, available on every supported on-prem release).
- Stored in `CredentialVault` under ref `redmine:<org_id>:<instance_id>` as JSON with the following fields (all on-prem variability lives here, single source of truth):
  - `base_url` — required; MUST start with `https://`.
  - `api_key` — required for `auth_mode=api_key`.
  - `auth_mode` — `"api_key"` (default) or `"basic"`.
  - `verify_ssl: bool` — default `True`; flipping it off triggers an audit log entry. Used for self-signed on-prem certs.
  - `rate_limit_qps: float` — default `2.0`. Per `(org_id, instance_id)` (D5).
  - `closed_status_ids: list[int]` — default `[]`. Fallback for pre-4.x instances missing `status.is_closed` (see Open Questions #4).
- Identity is verified at backfill start with `GET /users/current.json`. We persist the resolved user id; this is the **identity used for the permission lock** (see "Permission lock" below).
- TLS: enforced via `base_url` scheme check + `verify_ssl` flag above.

## Data Mapping — the central question

Redmine issues are append-only conversation streams: `issue.description` (set at creation) plus an ordered list of `journals[]` where each journal is either a notes-bearing comment or a metadata diff (`details[]`).

We pick **one row per `(issue, journal)` pair, plus one anchor row for the issue itself**, rather than one row per issue.

### Why not "1 issue = 1 row"?

- Loses temporal grain. The retriever cannot answer "what did we decide on 2025-09-12?" if all journals collapse into one body.
- Embeddings dilute. A 40-comment ticket would embed into a single chunk that averages out the actual decision moments.
- Citations break. Slack-KB Phase 1 already established that citations point at a single timestamp/source — multi-journal collapse cannot produce a stable `source_uri`.

### Why not "1 journal = 1 row, no anchor"?

- The issue's `description` (the original problem statement) is not a journal. Skipping it loses the problem framing that makes journals interpretable.

### Chosen layout

Every emitted `BackfillItem` carries the backbone-mandated fields: `source_type`, `source_ref`, `source_uri`, `body`, `parent_ref` (D3), `source_created_at` (D6), `source_updated_at` (D6), `acl_scope` (C1), plus the adapter's encoded `cursor_of(item)` (D2).

For each issue we emit:

1. One **issue anchor row** (`parent_ref = None`):
   - `source_type = "redmine_issue"`
   - `source_ref = "<issue_id>"`
   - `source_uri = "<base>/issues/<issue_id>"`
   - `body` = `subject` + `description` (markdown), redacted via `kb/redactor.py`.
   - `parent_ref = None`
   - `source_created_at = issue.created_on`
   - `source_updated_at = issue.updated_on`

2. Zero or more **journal rows** (children of the issue anchor), only for journals where `notes` is non-empty after trim:
   - `source_type = "redmine_journal"`
   - `source_ref = "<issue_id>#note-<journal_id>"`
   - `source_uri = "<base>/issues/<issue_id>#note-<journal_n>"` (n is journal display index, not id; we compute it client-side to match what users see)
   - `body` = notes markdown, redacted.
   - `parent_ref = "redmine_issue:<issue_id>"` (D3, first-class field)
   - `source_created_at = journal.created_on`
   - `source_updated_at = journal.created_on` (journals are immutable in Redmine)

Pure-metadata journals (only `details[]`, e.g. "status changed from New to Closed") are **dropped at the filter stage** and counted under `JobReport.skipped["metadata_only_journal"]`. They are noise for retrieval but their counts are surfaced in the dry-run report.

Wiki pages map to `source_type = "redmine_wiki"` 1:1 with the page (`parent_ref = None`, one row per page, like Confluence). Attachments, if MIME-eligible, become `source_type = "redmine_attachment"` rows tied to the parent issue/wiki by `parent_ref = "redmine_issue:<issue_id>"` or `parent_ref = "redmine_wiki:<page_id>"`.

## Signal Filters (Redmine-specific)

Applied in `BackfillJob.filter` stage, in order. Each rule increments `JobReport.skipped[<key>]` (D1) and contributes a line in the dry-run report.

| Rule                          | Definition                                                                              | Default | `skipped` key (D1)        |
|-------------------------------|-----------------------------------------------------------------------------------------|---------|---------------------------|
| `closed_only`                 | Skip issues whose `status.is_closed=False` OR custom `wontfix`/`duplicate` resolutions  | `True`  | `closed_old`              |
| `min_description_chars`       | Skip anchor rows with stripped description < N chars (default 40)                       | `True`  | `empty_description`       |
| `bot_authors`                 | Skip rows where `author.login` matches operator-supplied regex (e.g. `^(jenkins\|gitlab-ci)`) | `True`  | `auto_generated`          |
| `min_journal_chars`           | Skip journal rows with notes < N chars (default 30)                                     | `True`  | `empty_description`       |
| `metadata_only_journal`       | Skip journals with empty `notes` even if `details[]` is rich                            | `True`  | `metadata_only_journal`   |
| `private_notes`               | If `journal.private_notes=True`, drop unconditionally — these bypass project visibility | `True`  | `private_notes`           |
| `tracker_allow`               | Optional: only ingest issues whose tracker is in the allowlist (e.g. `Bug, Support`)    | unset   | `auto_generated`          |
| `acl_lock`                    | Item rejected by membership snapshot taken at discover-start (C1)                       | always  | `acl_lock`                |

`closed_only` reflects the heuristic that **resolved tickets are knowledge; open tickets are speculation**. Operators can flip it for triage-team use cases.

## Permission Lock

Redmine's permission model is project-membership + role-based, with private projects invisible to non-members. We re-use the common policy from earlier sub-projects: **"current membership wins."** Per backbone decision **C1**, the lock is taken **immediately before `discover` begins** and held for the entire job.

At discover-start (C1):

1. Resolve the API user with `/users/current.json`.
2. For each project in the job's `source_filter`, snapshot active members via `GET /projects/<id>/memberships.json` (preferred — returns the full member set in one call). Fall back to `/users/<id>.json?include=memberships` only when the project endpoint is forbidden.
3. Build the in-memory ACL set `{(project_id, member_user_id, role_name)}` for every project in scope. This is **the** ACL snapshot used for the rest of the job.
4. Every emitted `BackfillItem` gets `acl_scope = "redmine:project:<project_id>"` so the existing `kb/acl.py` filter at retrieval time can intersect with the **querying user's** Redmine memberships, not the backfill user's.
5. Items whose project is private and whose querying-user-side membership is unknowable at backfill time are still emitted with the project ACL marker; access is denied at query time, not backfill time. Items rejected at discover-start (e.g. project disappeared between job submission and snapshot) increment `JobReport.skipped["acl_lock"]`.

Implication: the ACL stored at backfill time is **the project membership**, never the backfill user's superset. A retriever asking on behalf of a viewer who is not in `project_id` will not see the row, even though the backfill ran with admin credentials. This matches Slack-KB Phase 1 behaviour.

Private projects: only ingested if the API user is a member. Private notes (`journal.private_notes=True`) are dropped entirely (see filter table) because their visibility key is **role-based** within a project, not membership-based, and we don't model role-level ACL in Phase 1.

## Rate Limit

Redmine **publishes no standard rate limit** in the core REST docs. On-prem operators routinely run behind reverse proxies (nginx, Cloudflare) that may impose their own limits. We therefore self-impose:

- **Default**: 2 req/s per `(org_id, instance_id)`, configurable via the credential blob's `rate_limit_qps` field. `instance_id = sha256(base_url)[:16]`.
- **Concurrency**: 1 in-flight HTTP request per instance (Redmine has no documented concurrency cap; many on-prem deployments share DB locks).
- **Backoff**: same `(60, 300, 1800)` ladder as `ConfluenceConnector`, triggered on 429 OR 5xx OR connection reset.
- **Honour `Retry-After`** if present (rare on Redmine, common when a CDN sits in front).
- Re-use `kb/quota.py` `HourlyPageBudget` with the new **instance-keyed dimension** `(org_id, instance_id)` introduced by backbone decision **D5**. The existing per-`project_id` key remains available; jobs that supply both are charged on the more restrictive of the two. Default cap 1000 pages/hour per `(org_id, instance_id)` — protects against runaway backfills on instances with 100k+ tickets shared across projects.

## Backfill Flow

`BackfillJob` invocation per `source_filter`:

```
source_filter = {
  "instance": "<vault_ref>",
  "project_id": "<numeric_or_identifier>",   # required, one project per job
  "include": ["issues", "wiki", "attachments"]
}
```

### Stages

0. **acl_lock** (C1): snapshot project memberships *before* discover starts; bind the snapshot to the job for its entire lifetime.
1. **discover** (D4 — `since`/`until` filtering happens here):
   - For `issues`: paginate `GET /issues.json?project_id=<id>&status_id=*&sort=updated_on&limit=100&include=journals,attachments&updated_on=>=<since>&updated_on=<=<until>` with offset pagination. Server-side `since`/`until` is honored on `updated_on`. Cursor is `(updated_on, issue_id)` (encoded per D2) to handle multiple issues sharing a timestamp.
   - For each issue's `journals[]`: in-memory cut by `journal.created_on ∈ [since, until]` (Redmine has no per-journal time filter on the API).
   - For `wiki`: `GET /projects/<id>/wiki/index.json`, then per page `GET /projects/<id>/wiki/<title>.json` if `updated_on` ∈ `[since, until]`.
2. **filter**: apply Redmine-specific signal filters above; each rejection increments the corresponding `JobReport.skipped[<key>]` counter (D1).
3. **redact**: hand each candidate body to `kb/redactor.py` — Redmine descriptions frequently contain emails, IPs, p4 paths, internal URLs.
4. **embed**: shared embedder; `token_budget` from `BackfillJob` input applies as a hard ceiling. Per-org monthly token ceiling (backbone operational policy) also enforced — whichever is hit first stops discover early and the adapter returns `partial=True` with the last-page cursor (D2).
5. **store**: pgvector + `org_knowledge` rows; uses Sub-project 1's idempotent `(source_type, source_ref, org_id)` upsert key. `parent_ref` is persisted as a 1st-class column (D3).

### Pagination & cursoring

Redmine offset pagination is unstable when issues are updated mid-walk (an issue updated to a newer `updated_on` shifts pages). Mitigation: sort by `updated_on:asc`, page forward, persist `(last_updated_on, last_issue_id)` after each page; if the next page returns an issue with the same `updated_on` and lower id, skip it as already-seen. This is the standard "keyset on (updated_on, id)" trick.

Per backbone decision **D2**, `JobReport.cursor: str | None` is opaque to the pipeline. This adapter implements:

```python
def cursor_of(item: BackfillItem) -> str:
    # `:` separator; ISO-8601 with `Z` is unambiguous and never contains `:` after the seconds field's last digit.
    return f"{item.source_updated_at.isoformat()}:{item.source_ref.split('#')[0]}"

# Example output: "2025-09-12T10:14:00Z:42117"
```

The pipeline never parses this string; only this adapter encodes/decodes it. This resolves the "structured cursor type" concern previously raised in Open Questions.

## Dry-run Output Example

```
breadmind kb backfill redmine --org acme --project ops --since 2025-09-01 --dry-run

Redmine backfill — DRY RUN
  instance: https://redmine.acme.internal/
  project:  ops (#7)
  window:   2025-09-01 → 2026-04-26 (today)

Discover
  issues fetched ............ 1 284
  wiki pages fetched ........  17
  attachments fetched .......  41

Filter (JobReport.skipped — D1 keys)
  kept issues ...................   412   (closed/resolved with description >= 40 chars)
  closed_old ....................   638   (open tickets, closed_only=True)
  empty_description .............   429   (118 anchors + 311 journals < min chars)
  auto_generated ................    92   (bot_authors regex: jenkins, gitlab-ci)
  metadata_only_journal ......... 2 905
  private_notes .................    47
  acl_lock ......................     0   (no membership-snapshot rejections)

Rows that WOULD be stored (BackfillItem with parent_ref shown for children — D3)
  redmine_issue        ....   412   (parent_ref=None)
  redmine_journal      ....   683   (parent_ref=redmine_issue:<id>, across kept issues)
  redmine_wiki         ....    14   (parent_ref=None; 3 dropped: < 40 chars)
  redmine_attachment   ....     9   (parent_ref=redmine_issue:<id>; 32 dropped: non-text or > 1 MB)
  ─────────────────────────────────
  TOTAL                ....  1 118

Redaction (preview)
  email matches .............  88
  internal_url matches ......  41
  api_key hard-blocks .......   0

Cost estimate
  embed tokens ..............  ~1.42 M  (within budget 5 M)
  pgvector rows .............   1 118
  est. wallclock ............  ~9 min @ 2 req/s

No changes written. Re-run without --dry-run to commit.
```

## CLI Entry Point

```
breadmind kb backfill redmine \
    --org <org_id_or_slug> \
    --project <project_id_or_identifier> \
    [--instance <vault_ref>]      # default: org's only redmine instance, error if multiple
    [--since YYYY-MM-DD]          # default: org's last_cursor or 90 days back
    [--until YYYY-MM-DD]          # default: now
    [--include issues,wiki,attachments]   # default: issues,wiki
    [--token-budget N]            # default: from org KB cost policy
    [--dry-run]
```

This is a thin wrapper over Sub-project 1's generic `breadmind kb backfill <connector>` dispatcher — the dispatcher resolves `redmine` → this connector class and forwards `source_filter` as `{instance, project_id, include}`.

## Test Strategy

- **Unit (mocked HTTP)** under `tests/kb/connectors/redmine/`:
  - `test_pagination_keyset.py`: `(updated_on, id)` ordering across boundary collisions.
  - `test_journal_split.py`: anchor + journals row generation; metadata-only journals dropped; private notes dropped.
  - `test_signal_filters.py`: each filter in isolation, default + override.
  - `test_auth.py`: API key header transport; `verify_ssl=False` audit log.
  - `test_acl_membership.py`: ACL scope written reflects project membership, not API user.
  - `test_redactor_integration.py`: PII patterns in `description` and journals are masked before embedding.
- **Contract (recorded fixtures)** using a pinned `redmine.acme.fixture/issues.json` payload; ensures schema drift on a real on-prem upgrade is detected.
- **E2E** following the Confluence pattern: a `build_for_e2e` factory that bypasses HTTP and feeds JSON fixtures into the real `BackfillJob.store` stage against testcontainers Postgres + pgvector.
- **Dry-run snapshot test**: exact CLI output above is asserted in CI to prevent silent format regressions.
- **Coverage target**: 90% line, 85% branch on the connector module; aligns with `confluence.py` baseline.

## Open Questions

### Resolved by Sub-project 1 backbone

- ~~**`SourceMeta.parent_ref` field**~~ → **Resolved by D3**. `BackfillItem.parent_ref: str | None` is a 1st-class field. Journal/attachment rows set it; anchor/wiki rows leave it `None`.
- ~~**Conflict with common-pipeline rate-limit primitive**~~ → **Resolved by D5**. `HourlyPageBudget` adds an `(org_id, instance_id)` dimension, backwards-compatible with the existing per-`project_id` key.
- ~~**Dual-purpose timestamp / structured cursor**~~ → **Resolved by D2**. `JobReport.cursor` stays `str | None` (opaque); this adapter encodes `(updated_on, issue_id)` as `"<iso>:<id>"` via its own `cursor_of()`. Pipeline never parses.

### Still open (Redmine-specific)

1. **Wiki history vs latest-only**. Redmine exposes wiki page versions via `/wiki/<title>/<version>.json`. **Proposed resolution: latest-only**, matching the Confluence connector — simpler, predictable token spend, history can be added later behind a flag without breaking existing data. (KB SME review still welcome but this spec proceeds with `latest-only`.)
2. **Attachment binary fetch & sandboxing**. `content_url` requires a separate authenticated `GET`; many corporate Redmines route attachments through a CDN with **different** auth. v1 plan: try API key header on `content_url`, fall back to skip + warn. Open: should we let operators provide an alternate attachment-auth blob?
3. **Custom fields**. On-prem Redmines often store the actually-useful info (root cause, customer id, sev) in `custom_fields[]`. Generic ingestion can leak PII or noise. Proposal: opt-in per-org list `custom_fields_to_index: ["Root cause", "Resolution"]`, others dropped. Defer to Sub-project 5 (per-source policy) if that lands.
4. **`status.is_closed` semantics on legacy on-prem (pre-Redmine-4.x)**. Pre-4.x instances may not expose `is_closed` on the status object via JSON. Fallback: operator-supplied `closed_status_ids: [5, 6, 7]` list in the credential blob. Default empty → `closed_only` becomes a no-op on those instances with a warning log. Confirm whether we want to ship the fallback in v1 or defer to a v1.1.

## Out of scope (this spec)

- Realtime / webhook ingestion. Redmine has no first-class webhook system in core; that is a separate "live connector" design.
- Two-way write-back (creating issues from BreadMind). KB ingest is read-only.
- Cross-instance dedup. If the same ticket lives in two mirrored Redmines we ingest twice; dedup is an org-level concern handled by `org_knowledge` policy, not the connector.
