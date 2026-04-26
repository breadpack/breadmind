# Backfill Pipeline + Slack Adapter — Design Spec

**Status:** draft
**Author:** Architect agent (Sub-project 1 of "외부 채널 History 일괄 backfill" series)
**Date:** 2026-04-26
**Sister specs (concurrent):** Notion (B), Confluence (C), Redmine (D) — all consume the contract defined here.
**Single source of truth:** the `BackfillJob` interface, schema additions, and dry-run output format defined in this document. Sister adapters MUST conform.

---

## 1. Overview & Goals

### What we are building
1. A **common backfill pipeline** (`src/breadmind/kb/backfill/`) sitting alongside (not replacing) the existing incremental `BaseConnector` flow in `src/breadmind/kb/connectors/`. It implements one well-defined lifecycle: `discover → filter → redact → embed → store`, with a token-budget gate, dry-run preview, resumable progress, and uniform `JobReport` output.
2. A **Slack adapter** (`SlackBackfillAdapter`) as the reference implementation, covering `conversations.history` + `conversations.replies` for explicitly-selected channels and time windows.
3. A **CLI entrypoint** (`breadmind kb backfill slack ...`) that lets an operator preview cost, then opt-in execute.

### What we are NOT building
- **No automatic backfill on connect.** Backfill never starts implicitly. Incremental ingestion remains the default.
- **No retrieval-time time weighting.** `source_created_at` and `source_updated_at` are *stored* but the scorer that uses them ships in a follow-up spec. `parent_ref` is stored similarly; the parent/child boost ships with the same follow-up.
- **No Web UI.** CLI + programmatic API only in this phase.
- **No retroactive permission resolution.** ACL is evaluated at job start using *current* membership; we do not replay `org_project_members` history.
- **No connector-specific signal logic in the pipeline.** Signal heuristics live inside each `BackfillJob.filter()` implementation; the pipeline only orchestrates.

### Guardrails (re-stated, binding)
| Guardrail | Mechanism |
| --- | --- |
| User must explicitly select channel + window | `source_filter` and `since/until` are required, no defaults |
| PII redaction strengthened | Pipeline calls `Redactor.abort_if_secrets()` then `Redactor.redact()` per item, before embed |
| Signal filter to drop noise | `BackfillJob.filter()` applies per-source heuristics |
| Token budget cap + progress | `token_budget` (hard stop) + `JobReport` running counters |
| Dry-run preview | `dry_run=True` runs `discover → filter` only, returns estimate, never embeds/stores |
| Source timestamp metadata | `source_created_at` + `source_updated_at` columns on `org_knowledge` (new); both are 1st-class `BackfillItem` fields. Time-weighted retrieval ships in a follow-up spec. |
| Parent reference for thread/comment rollup | `parent_ref` 1st-class field on `BackfillItem` and `org_knowledge` (new) — encodes `(source_kind, source_native_id)` of the parent row when applicable. |
| Permission lock at job start | Membership snapshot resolved once in `BackfillJob.prepare()` (immediately before `discover()`), never re-checked. Per-item ACL is **labelled only** (compare author against snapshot; mismatch → `skipped["acl_lock"]`); no per-item API call. |
| Per-org monthly token ceiling | `kb_backfill_jobs` budget tracker (per-org, per-month, backfill-only). `QuotaTracker` (per-user) remains the incremental-flow ceiling. |

---

## 2. Architectural Position

```
src/breadmind/kb/
├── connectors/                  # (existing) incremental BaseConnector world
│   ├── base.py
│   └── confluence.py
└── backfill/                    # (NEW) bulk-history pipeline
    ├── base.py                  # BackfillJob ABC + JobReport + JobProgress
    ├── runner.py                # orchestrator: discover→filter→redact→embed→store
    ├── checkpoint.py            # resumability (DB-backed)
    ├── slack.py                 # SlackBackfillAdapter (this sub-project)
    ├── notion.py                # (sister sub-project B)
    ├── confluence.py            # (sister sub-project C — bulk variant of existing)
    └── redmine.py               # (sister sub-project D)
```

The two layers are deliberately separate:
- `connectors/` answers *"what changed since cursor X?"* — small, frequent, automatic.
- `backfill/` answers *"give me everything in window [since, until] for these scopes, once."* — large, manual, opt-in.

They share `Redactor`, `KnowledgeExtractor`, `EmbeddingService`, and the `org_knowledge`/`kb_sources` tables. They do **not** share cursors: backfill state lives in a new `kb_backfill_jobs` row, never touching `connector_sync_state`.

---

## 3. `BackfillJob` Abstract Interface (binding contract)

```python
# src/breadmind/kb/backfill/base.py
from __future__ import annotations
import abc, uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar


@dataclass(frozen=True)
class BackfillItem:
    """One unit produced by discover() and consumed downstream."""
    source_kind: str            # 'slack_msg' | 'notion_page' | 'confluence_page' | 'redmine_issue'
    source_native_id: str       # Slack ts, Notion page id, etc. — stable across runs
    source_uri: str             # Permalink for citations
    source_created_at: datetime # UTC, source-supplied; immutable creation time
    source_updated_at: datetime # UTC, source-supplied; last-edit time (== created_at if never edited)
    title: str                  # Short label (channel name, page title, ...)
    body: str                   # Raw text (pre-redaction)
    author: str | None          # Source-native user id; pipeline never PIIs this
    parent_ref: str | None = None  # "<source_kind>:<source_native_id>" of parent row, or None.
                                   # Used by retrieval for parent/child boost (Slack thread reply →
                                   # parent message; Redmine journal → issue; Notion subpage → parent).
    extra: dict[str, Any] = field(default_factory=dict)  # adapter-private metadata


@dataclass
class JobProgress:
    """Mutable counters updated by runner; persisted to kb_backfill_jobs."""
    discovered: int = 0
    filtered_out: int = 0
    redacted: int = 0
    embedded: int = 0
    stored: int = 0
    skipped_existing: int = 0
    errors: int = 0
    tokens_consumed: int = 0
    last_cursor: str | None = None  # adapter-defined opaque resume token


@dataclass(frozen=True)
class JobReport:
    """Final output of run() / dry_run()."""
    job_id: uuid.UUID
    org_id: uuid.UUID
    source_kind: str
    dry_run: bool
    estimated_count: int        # post-filter, pre-budget items
    estimated_tokens: int       # sum of len(body)//4 per filtered item
    indexed_count: int          # 0 in dry-run
    skipped: dict[str, int] = field(default_factory=dict)
    # ^ reason → count map. Total drop = sum(skipped.values()).
    # Reserved keys used by the runner: "skipped_existing" (dedup hit).
    # Adapter-defined keys (Slack): "signal_filter_short", "signal_filter_bot",
    # "signal_filter_no_engagement", "signal_filter_mention_only",
    # "redact_dropped" (SecretDetected during redact),
    # "acl_lock" (author not in membership snapshot),
    # "archived" (channel/page archived between discover and store).
    # Each adapter MUST publish its own key set in its concrete spec section.
    errors: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    sample_titles: list[str] = field(default_factory=list)  # up to 10, for dry-run preview UX
    budget_hit: bool = False    # True if we stopped early on token_budget
    cursor: str | None = None
    # ^ Opaque resume token = adapter's cursor_of(last_processed_item).
    # The pipeline never parses it; the adapter owns the format
    # (e.g. Slack: "<ts_ms>:<channel>:<message_ts>").


class BackfillJob(abc.ABC):
    """Single-source-of-truth backfill contract.

    Lifecycle (driven by BackfillRunner, not subclasses):
        await job.prepare()             # one-shot: ACL snapshot, auth, rate-limit handle
        async for item in job.discover():
            if not job.filter(item):     # cheap, sync, signal heuristics
                continue
            redacted = await pipeline.redact(item)
            embedded = await pipeline.embed(redacted)
            await pipeline.store(embedded)

    Subclasses MUST set ``source_kind`` and implement ``prepare``,
    ``discover``, and ``filter``. They MUST NOT call redact/embed/store
    themselves — those steps are owned by the runner so the pipeline is
    uniform across adapters.
    """

    source_kind: ClassVar[str] = ""

    def __init__(
        self,
        *,
        org_id: uuid.UUID,
        source_filter: dict[str, Any],   # adapter-shaped: e.g. {'channels': ['#eng', '#ops']}
        since: datetime,                 # required, UTC
        until: datetime,                 # required, UTC
        dry_run: bool,
        token_budget: int,               # hard cap on cumulative tokens; runner stops at >=
        config: dict[str, Any] | None = None,
    ) -> None: ...

    @abc.abstractmethod
    async def prepare(self) -> None:
        """One-shot setup, called by the runner immediately before discover().
        MUST resolve current ACL/membership and store it immutably on self
        (the membership snapshot). MUST validate all selected scopes are
        allowed. Raises PermissionError if any scope is denied. The runner
        does NOT call this again for the lifetime of the job."""

    @abc.abstractmethod
    def discover(self) -> AsyncIterator[BackfillItem]:
        """Yield raw items satisfying ``self.since <= item.source_updated_at < self.until``
        for the requested scopes. Range filtering is THE adapter's responsibility:
        if the source supports server-side range (Slack `oldest`/`latest`,
        Notion `last_edited_time` filter, Confluence CQL `lastmodified`,
        Redmine `updated_on`), use it; otherwise the adapter MUST cut
        client-side before yielding. The pipeline performs NO post-yield
        timestamp filtering. Order is not guaranteed but adapters SHOULD
        yield oldest-first so resume cursors are monotonic."""

    @abc.abstractmethod
    def filter(self, item: BackfillItem) -> bool:
        """Return True to keep, False to drop. MUST be pure and cheap.
        Signal heuristics live here. ACL labelling (compare item.author against
        the membership snapshot from prepare()) also lives here as a special
        case — but rather than dropping, the adapter SHOULD emit the item with
        a marker in extra so the runner counts it under
        skipped["acl_lock"]. NO per-item API calls allowed (N+1 ban)."""

    @abc.abstractmethod
    def instance_id_of(self, source_filter: dict[str, Any]) -> str:
        """Return the workspace/instance identifier for rate-limit accounting.
        Slack: team_id. Notion: workspace_id. Confluence: base_url host.
        Redmine: stable hash of base_url. The pipeline keys
        ``HourlyPageBudget`` on (org_id, instance_id) so two orgs sharing
        a workspace, or one org spanning two workspaces, do not silently
        merge their budgets."""

    # Optional hooks; default no-op
    async def teardown(self) -> None: ...
    def cursor_of(self, item: BackfillItem) -> str:
        """Return an opaque resume token for this item. Default: source_native_id.
        Adapters MAY override to encode richer state (Slack default override:
        ``f"{ts_ms}:{channel_id}:{message_ts}"``). The runner treats this string
        as opaque — it is stored verbatim in kb_backfill_jobs.last_cursor and
        passed back to the adapter on resume."""
```

### Adapter contract — single-line invariants

1. **Range filter is adapter-only.** Adapter yields exclusively items where `since <= source_updated_at < until`. Pipeline does no post-cut.
2. **`cursor` opacity.** `JobReport.cursor` and `kb_backfill_jobs.last_cursor` are opaque to the pipeline; only `cursor_of` knows the format.
3. **Skip reasons are explicit.** Every dropped item bumps exactly one key in `JobReport.skipped`. Adapters publish their key set in their concrete spec section.
4. **ACL is labelled, not enforced.** Per-item API lookups are banned; mismatch against the membership snapshot is a label only.
5. **Instance-keyed rate limit.** `HourlyPageBudget` is keyed by `(org_id, instance_id)`; the legacy `(org_id,)` key is honoured for backwards compatibility but new code MUST use the instance-keyed dimension.

### Why these choices
- **Runner owns redact/embed/store**, not the adapter — this is what guarantees uniform PII handling and DB writes regardless of source. Adapters that try to skip redaction silently are physically prevented.
- **`filter()` is sync and cheap** — async filters tempt people to do API lookups in the hot path. If an adapter needs richer filtering (e.g. fetching reactions), it must do it in `discover()` and stash the data in `BackfillItem.extra`.
- **`token_budget` is enforced by the runner**, not the adapter, so it's consistent.
- **`source_filter` is `dict[str, Any]`** rather than typed — adapters publish their own JSON Schema for it; the CLI validates against that schema. This is the only place the contract is intentionally loose.

---

## 4. Data Flow

```
                     CLI / API entrypoint
                            │
                            ▼
                  ┌──────────────────────┐
                  │ BackfillRunner       │
                  │  (kb/backfill/runner)│
                  └──────────────────────┘
                            │
        ┌───────────────────┼─────────────────────────────────┐
        │ prepare()         │ token_budget gate               │
        │  - ACL snapshot   │ progress checkpoints (every N)  │
        │  - auth handle    │                                 │
        ▼                   ▼                                 ▼
   ┌─────────┐       ┌─────────────┐                  ┌──────────────┐
   │ discover│──────▶│ filter()    │──────────────────▶│  dry_run? ──▶│ JobReport
   │ (async) │       │ signal cut  │   if dry_run     └──────┬───────┘
   └─────────┘       └─────────────┘                         │ no
                                                             ▼
                                                ┌────────────────────────┐
                                                │ Redactor.abort_if_     │
                                                │   secrets() then       │
                                                │   redact()             │
                                                └────────────────────────┘
                                                             │
                                                             ▼
                                                ┌────────────────────────┐
                                                │ EmbeddingService.embed │
                                                │ (token charge here)    │
                                                └────────────────────────┘
                                                             │
                                                             ▼
                                                ┌────────────────────────┐
                                                │ INSERT org_knowledge   │
                                                │   + kb_sources         │
                                                │   + UPDATE             │
                                                │     kb_backfill_jobs   │
                                                └────────────────────────┘
```

Notes:
- The runner increments `JobProgress.tokens_consumed` *before* calling embed (using `len(body)//4` cheap estimate) and bails if `>= token_budget`. The actual embed call cost is reconciled afterwards.
- Checkpoints are written to `kb_backfill_jobs.last_cursor` (= `job.cursor_of(last_item)`) every 50 items or every 30 seconds (whichever first). This is the resume point on restart.
- Every dropped item increments exactly one key in `JobReport.skipped` (the dict counter). The runner emits keys `"skipped_existing"` (dedup hit) and `"redact_dropped"` (SecretDetected); the adapter contributes its own keys via `filter()` returning False **and** stamping `extra["_skip_reason"]` (or by raising the runner-recognised `Skipped(reason)` exception inside discover()). Total dropped == `sum(skipped.values())`.
- All redacted bodies replace `<USER_n>` tokens with stable per-item hashes — restoration maps are not persisted (backfill output is not user-restored, unlike the live LLM path). Author gating: `kb/redactor.py`'s Slack `<@Uxxxx>` mention pattern is reused to pseudonymise `BackfillItem.author` at store time, including for authors who later left the channel (see decision P3 in §11).

---

## 5. DB Schema Changes

**Migration:** `010_kb_backfill.py` (depends on `009_episodic_org_id`).

```sql
-- Extend org_knowledge with source provenance for backfilled rows.
ALTER TABLE org_knowledge
    ADD COLUMN IF NOT EXISTS source_kind         TEXT,
    ADD COLUMN IF NOT EXISTS source_native_id    TEXT,
    ADD COLUMN IF NOT EXISTS source_created_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_updated_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS parent_ref          TEXT;
    -- parent_ref encodes "<source_kind>:<source_native_id>" of parent row.
    -- NULL for top-level items. Retrieval uses it for parent/child boost
    -- (Slack thread reply → parent message; Redmine journal → issue;
    -- Notion subpage → parent). NOT a foreign key — parent may be on a
    -- different source or absent.

-- Dedup guard: same (org, source_kind, native_id) is one logical knowledge row.
-- Timestamps are deliberately NOT part of the dedup key — re-edits of the
-- same source row supersede via superseded_by, not via a new index entry.
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

-- New: backfill job tracking + resumability.
CREATE TABLE IF NOT EXISTS kb_backfill_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
    source_kind     TEXT NOT NULL,
    source_filter   JSONB NOT NULL,
    instance_id     TEXT NOT NULL,    -- adapter's instance_id_of(source_filter); rate-limit dimension
    since_ts        TIMESTAMPTZ NOT NULL,
    until_ts        TIMESTAMPTZ NOT NULL,
    dry_run         BOOLEAN NOT NULL,
    token_budget    BIGINT NOT NULL,
    status          TEXT NOT NULL,    -- 'pending'|'running'|'paused'|'completed'|'failed'|'cancelled'
    last_cursor     TEXT,             -- opaque, == adapter's cursor_of(last_item)
    progress_json   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- serialized JobProgress
    skipped_json    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- serialized JobReport.skipped reason→count
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error           TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kb_backfill_org_status
    ON kb_backfill_jobs (org_id, status, created_at DESC);

-- New: per-org monthly token ceiling for backfill (decision P1, §11).
-- Distinct from QuotaTracker (per-user, incremental flow).
CREATE TABLE IF NOT EXISTS kb_backfill_org_budget (
    org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
    period_month    DATE NOT NULL,                -- first day of UTC month
    tokens_used     BIGINT NOT NULL DEFAULT 0,
    tokens_ceiling  BIGINT NOT NULL,              -- per-org monthly cap (configured)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, period_month)
);
```

**One-line summary:** Add `(source_kind, source_native_id, source_created_at, source_updated_at, parent_ref)` to `org_knowledge` (with a unique partial dedup index plus secondary indexes on updated_at and parent_ref), a `kb_backfill_jobs` table (with `instance_id` and `skipped_json`), and a `kb_backfill_org_budget` table for the per-org monthly token ceiling.

---

## 6. Slack Adapter (concrete)

> **Naming convention.** Concrete backfill classes are named `<Source>BackfillAdapter`
> (so: `SlackBackfillAdapter`, `NotionBackfillAdapter`, `ConfluenceBackfillAdapter`,
> `RedmineBackfillAdapter`). This is deliberately distinct from the legacy
> incremental connectors (`ConfluenceConnector`, etc.) — backfill and incremental
> live in separate class hierarchies and separate packages (`kb/backfill/` vs
> `kb/connectors/`).

### 6.1 Source filter schema
```jsonc
{
    "channels":      ["C0123456", "C0987654"],   // required, ≥1; channel IDs (not names)
    "include_threads":  true,                    // default true
    "include_dms":      false                    // hard-locked false in Phase 1
}
```
Channel name → ID resolution happens in the CLI before constructing the job (uses `conversations.list`); `BackfillJob` only sees IDs to keep `prepare()` deterministic.

### 6.2 API usage
| Slack call | Purpose | Pagination |
| --- | --- | --- |
| `conversations.history` | Top-level messages in `[since, until]` | `cursor` + `limit=200`, `oldest`/`latest` set |
| `conversations.replies` | Thread replies for any `thread_ts` discovered | `cursor` + `limit=200`, called per parent |
| `conversations.info` | Verify membership at `prepare()` time | one call per channel |

### 6.3 Rate limit & retry
- Slack Tier 3 = ~50 req/min on `conversations.history`. Adapter respects `Retry-After` header on 429, with the same exponential backoff schedule used by `ConfluenceConnector`: `(60, 300, 1800)` seconds.
- `HourlyPageBudget` (default `limit=1000` pages/hour) is keyed on `(org_id, instance_id)` per decision **D5** in §3. The legacy `(org_id,)` key remains accepted for backwards compatibility but new code MUST emit the instance-keyed dimension. For Slack, `SlackBackfillAdapter.instance_id_of(source_filter)` returns the workspace `team_id` (resolved via `auth.test` once at `prepare()` time and cached on the adapter). Backfill runs that exceed the per-`(org_id, team_id)` budget **pause** (do not error) and persist `last_cursor` so a later resume picks up.
- Slack API token: looked up via `CredentialVault.retrieve(credentials_ref)` exactly as Confluence does.

### 6.3a Permission lock (ACL)
- `SlackBackfillAdapter.prepare()` calls `conversations.members` once per channel, unions the results, and stores the immutable set on `self._membership_snapshot: frozenset[str]`. This is the only ACL fetch for the lifetime of the job.
- `discover()` does **NOT** make any per-message membership API call. Where the Slack payload supplies `user`/`bot_id` cheaply we set `BackfillItem.author` from it.
- `filter()` compares `item.author` against `self._membership_snapshot`. On mismatch, the adapter stamps `item.extra["_skip_reason"] = "acl_lock"` and returns `False`; the runner records `skipped["acl_lock"] += 1`. **No per-item API calls.**
- Per decision **P3** in §11: messages from authors who have since left the channel ARE included (their content was shared with members at the time). Author identifiers are pseudonymised at store time by `kb/redactor.py`'s Slack mention pattern (`<@U[A-Z0-9]+>` family — extended to bare `Uxxxx`/`Wxxxx` IDs in `BackfillItem.author`).

### 6.4 Signal filter (default heuristics)

`SlackBackfillAdapter.filter()` drops messages (returning `False` and stamping `extra["_skip_reason"]` so the runner increments the matching `skipped` key) where ANY of:

1. **Length:** `len(body.strip()) < 5` characters (after stripping mentions/emoji-only). → `skipped["signal_filter_short"]`.
2. **Bot message:** `extra["subtype"] in {"bot_message", "channel_join", "channel_leave", "channel_topic", "channel_purpose"}`. → `skipped["signal_filter_bot"]`.
3. **No engagement & no thread:** `extra["reaction_count"] == 0 AND extra["reply_count"] == 0`. → `skipped["signal_filter_no_engagement"]`.
4. **Pure mention/emoji:** message body, after stripping `<@...>`, `<#...>`, and unicode emoji, is empty or matches `^\W*$`. → `skipped["signal_filter_mention_only"]`.

ACL mismatch (per §6.3a) bumps `skipped["acl_lock"]`. Channel archived between dry-run and confirm bumps `skipped["archived"]` only when the runner observes mid-flight archival; per decision **P4** in §11, *pre-flight* archival is fail-closed (job aborts before any work).

Threads are kept *if the parent passes* (since the parent carries the question context); replies are concatenated into the parent's body up to a 4000-char chunk budget (matching `ConfluenceConnector._CHUNK_CHAR_BUDGET`). Each thread becomes one `BackfillItem`, not N items, to avoid orphan replies polluting retrieval. The thread item's `parent_ref` is `None` (it IS the parent); individual reply rows are NOT emitted as separate items in Phase 1.

These thresholds are tunable via `config={"min_length": ..., "drop_zero_engagement": ...}` on `SlackBackfillAdapter.__init__`. Defaults are set so a typical eng channel keeps roughly 20-30% of messages.

### 6.5 `source_native_id` rule
- Top-level message: `f"{channel_id}:{ts}"`
- Thread (treated as one item): `f"{channel_id}:{thread_ts}:thread"`

These are stable across re-runs, so `uq_org_knowledge_source_native` cleanly dedupes if a backfill is restarted or overlaps an earlier run.

### 6.6 Resume cursor format
- `SlackBackfillAdapter.cursor_of(item)` returns `f"{int(item.source_updated_at.timestamp() * 1000)}:{channel_id}:{message_ts}"`. Monotonic in `source_updated_at`, channel-scoped, and reversible to a Slack `oldest=` value on resume.
- The pipeline never parses this string; only `SlackBackfillAdapter._cursor_to_oldest()` (private) does.

### 6.7 Range filter compliance (D4)
- Slack supports server-side range via `oldest`/`latest` on `conversations.history`. The adapter sets both from `self.since`/`self.until` and yields without further client-side cuts. `conversations.replies` does NOT support range; the adapter applies a client-side cut on `ts` for each reply against the same window before deciding whether to fold it into the parent item.

---

## 7. Dry-run Output Format

CLI text output (and `JobReport.__repr__`-equivalent JSON when `--json`):

```
$ breadmind kb backfill slack \
    --org 8c4f-... --channel C0123456 --channel C0987654 \
    --since 2026-01-01 --until 2026-04-01 --dry-run

Backfill DRY-RUN — Slack
========================
Org:             8c4f-...-9a (project: pilot-alpha)
Source:          slack_msg
Instance:        T012345 (workspace acme-eng)
Channels:        #engineering (C0123456), #ops (C0987654)
Window:          2026-01-01T00:00:00Z → 2026-04-01T00:00:00Z  (filter: source_updated_at, half-open)
Token budget:    500,000  (job)  /  per-org monthly remaining: 7,200,000 / 10,000,000
Membership lock: 7 members snapshotted at 2026-04-26T13:42:11Z (per-item ACL: label-only)

Discovery
---------
Discovered messages:        12,481
  - top-level:               9,204
  - thread roots:            3,277
After signal filter:         3,512   (drop rate 71.9%)
Skipped (by reason)
  - signal_filter_short:       812
  - signal_filter_bot:         640
  - signal_filter_no_engagement: 7,103
  - signal_filter_mention_only:  414
  - acl_lock:                    0
  - archived:                    0
  - skipped_existing:            0  (dry-run does not touch DB)

Cost estimate
-------------
Estimated tokens (body):    ~412,000   (within budget: yes)
Estimated embeddings:        3,512
Estimated DB rows:           3,512 org_knowledge + 3,512 kb_sources

Sample titles (10 of 3,512)
----------------------------
  [#engineering] postgres connection pool tuning recap
  [#engineering] re: deploy rollback procedure clarified
  [#ops]         k8s upgrade 1.29 → 1.30 lessons
  [#engineering] pgvector HNSW index tuning thread
  [#ops]         on-call runbook for redis OOM
  [#engineering] auth token rotation gotchas
  [#ops]         backup verification cron deep-dive
  [#engineering] mypy strict mode rollout retro
  [#engineering] feature-flag service migration plan
  [#ops]         incident 2026-02-14 root cause

No data was indexed.
To run for real: re-issue without --dry-run.
```

The fields above are stable: sister adapters (Notion/Confluence/Redmine) MUST emit the same sections (`Org / Source / Instance / Window / Token budget / Membership lock / Discovery / Skipped (by reason) / Cost estimate / Sample titles`) in the same order. Per-source breakdown lines under "Discovery" and per-source reason keys under "Skipped (by reason)" are adapter-specific, but the dict-shaped `skipped` map is universal.

---

## 8. CLI / API Entrypoints

### CLI (Phase 1)
```bash
# Dry-run (always run this first)
breadmind kb backfill slack \
    --org <org-uuid> \
    --channel <channel-name-or-id> [--channel <...>]... \
    --since YYYY-MM-DD \
    --until YYYY-MM-DD \
    [--token-budget 500000] \
    [--include-threads/--no-threads] \
    [--min-length 5] \
    --dry-run

# Real run (requires explicit --confirm to avoid accidental large jobs)
breadmind kb backfill slack <same flags> --confirm

# Resume a previously-paused or failed job
breadmind kb backfill resume <job-uuid>

# List recent jobs
breadmind kb backfill list --org <org-uuid> [--status running|failed|completed]

# Cancel a running job
breadmind kb backfill cancel <job-uuid>
```

CLI lives at `src/breadmind/cli/kb_backfill.py` and registers under the existing `breadmind kb ...` Click group.

### Programmatic API
```python
from breadmind.kb.backfill import BackfillRunner
from breadmind.kb.backfill.slack import SlackBackfillAdapter

adapter = SlackBackfillAdapter(
    org_id=org_id,
    source_filter={"channels": ["C0123456"], "include_threads": True},
    since=since, until=until,
    dry_run=False,
    token_budget=500_000,
)
report = await BackfillRunner(db=db, redactor=redactor, embedder=embedder).run(adapter)
# report.skipped is a dict[str, int]; report.cursor is the opaque resume token.
```

Web UI is **explicitly out of scope** for this sub-project (deferred follow-up).

---

## 9. Error Handling & Resumability

### Per-item errors
- Caught by the runner, logged + counted in `JobProgress.errors`. Job continues. If `errors > 0.10 * discovered` after the first 200 items, the runner aborts with status `failed` (sanity check against systemic problems like a wrong vault credential).

### Pause / resume
- Every 50 items OR every 30 seconds: runner upserts `kb_backfill_jobs.last_cursor = job.cursor_of(last_item)` and `progress_json`.
- Restart: `breadmind kb backfill resume <job-id>` reloads the row, asks the adapter to re-`discover()` *starting from* `last_cursor` (adapters MUST honour this — for Slack, that means setting `oldest = ts_of(last_cursor)`).
- A resumed job with `dry_run=True` is a no-op (just re-emits the report). Resume only meaningfully applies to real runs.

### Hard failures
- `PermissionError` from `prepare()` → status `failed`, no DB writes, full reason in `kb_backfill_jobs.error`.
- `ChannelArchived` between dry-run and confirm (per decision **P4** in §11) → **fail-closed**. `prepare()` calls `conversations.info` and aborts with `status='failed'`, error message: `"channel <id> archived since dry-run; re-run dry-run to refresh and try again."`. No partial work performed. If a channel is archived *mid-run* (e.g. very long backfill), the runner observes the API error, marks remaining items in that channel as `skipped["archived"]`, and continues with the other channels.
- `SecretDetected` from redactor on any single item → that item is skipped, `JobReport.skipped["redact_dropped"] += 1`, body NOT logged. Job continues. (Distinct from `errors`: redaction-driven skips are expected, not errors.)
- `BudgetExceeded` (hourly page budget on `(org_id, instance_id)`) → status `paused`, resume token saved. **NOT** `failed`.
- `OrgMonthlyBudgetExceeded` (per-org monthly token ceiling from `kb_backfill_org_budget`, decision **P1**) → status `paused`, resume token saved, error message references the ceiling so an admin can lift it. **NOT** `failed`.
- `token_budget` (per-job) exhausted → status `completed` with `budget_hit=True`. The user can re-run with a higher budget; dedup guard (Section 5) prevents double-indexing.

---

## 10. Test Strategy

### Unit (`tests/kb/backfill/`)
- `test_base.py` — `BackfillJob` ABC enforcement: missing `source_kind`/abstract methods raise `TypeError`; `cursor_of` default behaviour; `JobProgress` math.
- `test_runner.py` — runner orchestration with a stub `BackfillJob`: confirms order is `discover→filter→redact→embed→store`, that `dry_run=True` skips redact/embed/store, that `token_budget` halts mid-iteration, that errors > 10% threshold aborts.
- `test_slack_filter.py` — each signal heuristic in isolation; threshold edge cases (length=4 vs 5, reactions=0 vs 1, mention-only regex).
- `test_slack_discover.py` — fake `aiohttp` session returning canned `conversations.history` + `conversations.replies` payloads, including pagination, 429 with `Retry-After`, thread roll-up.
- `test_checkpoint.py` — pause-mid-run, restart from cursor, dedup via `uq_org_knowledge_source_native`.

### Integration (`tests/integration/kb/backfill/`)
- Testcontainers Postgres + migration `010` applied. Run a small in-memory `SlackBackfillAdapter` (using a fake Slack client preloaded with 200 messages across 2 channels) end-to-end. Assert: row count in `org_knowledge`, `kb_sources` citation rows correct, `kb_backfill_jobs.status='completed'`, `progress_json` consistent with `JobReport`.
- A second integration test exercises resume: kill the runner mid-flight (raise inside the embedder stub on item 73), restart with `resume`, assert final count == expected and no duplicates.

### E2E (`tests/e2e/kb_backfill_slack.py`)
- Marked `slow + requires-slack-token`. Off by default in CI. Hits a sandbox Slack workspace with 3 seeded channels containing pre-known noise vs signal messages, verifies dry-run estimates within ±5% of real-run indexed count.

### Coverage target
- Unit + integration ≥ 90% for `kb/backfill/`. CLI gets a single golden-output snapshot test (the Section 7 example, against a fake job).

---

## 11. Decisions & Remaining Open Questions

### Decided in this spec (binding for sister adapters)

- **P1 — Embedding cost charging.** Backfill gets its own per-org monthly token ceiling tracked in `kb_backfill_org_budget` (see §5). `QuotaTracker` (per-user, daily) remains the incremental-flow ceiling, untouched. The two are independent. When the per-org monthly ceiling is hit, the running job pauses (resume token saved) — it does NOT fail; an admin can lift the ceiling and the user resumes via `breadmind kb backfill resume <job-uuid>`.

- **P3 — Reply visibility on private threads.** Messages from authors who later left the channel ARE included (the content was shared with members at the time of authorship; redaction handles privacy). `kb/redactor.py`'s Slack mention pattern (`<@U[A-Z0-9]+>`, extended to bare `Uxxxx`/`Wxxxx` IDs at the `BackfillItem.author` site) pseudonymises the author at store time. Per-item ACL labelling (§6.3a) is purely a label — the row is still indexed unless another rule drops it.

- **P4 — Channel archive between dry-run and confirm.** **Fail-closed.** `prepare()` re-checks each channel's archive flag via `conversations.info`. If any selected channel transitioned to archived since dry-run, the job aborts with status `failed` and error message: `"channel <id> archived since dry-run; re-run dry-run to refresh and try again."`. No partial work performed. Mid-run archival (long jobs) is handled gracefully: remaining items in that channel go to `skipped["archived"]`, the rest of the channels continue.

### Still open (return to upper review — do NOT auto-decide)

- **Q-2 — Re-backfill overlap semantics.** If an operator backfills `[Jan, Apr]` then later runs `[Mar, May]`, March overlaps. The unique index dedupes silently. Is silent dedup right, or should the CLI warn (`"3,012 of 4,500 already indexed"`) before proceeding?

- **Q-5 — Sister-adapter `source_filter` validation.** This spec leaves `source_filter` typed as `dict[str, Any]`. Should sister adapters publish JSON Schema that the CLI validates against, or is per-adapter `validate_source_filter()` method enough?

- **Q-6 — Embedding model drift across runs.** If `EmbeddingService` switches backends mid-job (e.g. fastembed→ollama), embeddings become heterogeneous within one `org_knowledge` table. Acceptable for Phase 1, or do we pin the model per job and refuse to start if the configured backend differs?

(3 decisions, 3 open questions.)

---

## 12. Slack-specific decisions that affect sister adapters

These are decisions made here that sister specs (B/C/D) MUST be aware of, because they shape the contract:

1. **Threads collapse to one `BackfillItem`.** The "rollup unit" pattern — Slack thread → 1 item — is the precedent for "Notion page with subpages → 1 item per leaf, parent skipped" and "Redmine issue + comments → 1 item per issue". Sister specs should explicitly state their rollup rule.

2. **`source_native_id` format is adapter-defined but MUST be stable across re-runs.** The unique partial index `uq_org_knowledge_source_native` is a hard contract: collisions cause `IntegrityError`, not silent overwrites. Sisters must pick a format that survives source-side renames (e.g. Notion: page UUID, NOT page title; Confluence: page id, NOT space+title).

3. **`source_filter` shape is adapter-specific** but the *required keys* pattern (Slack requires `channels`) sets the precedent. Sisters should require the analogous narrow scope (Notion: `spaces`/`databases`; Confluence: `space_keys`; Redmine: `project_ids`). No adapter should default to "everything visible".

4. **Dropping zero-engagement is THE Slack signal heuristic.** Sister adapters need their own equivalents (Notion: skip pages with `<3 blocks`; Confluence: skip pages with `<200 chars`; Redmine: skip issues `status=new AND comments=0`). The pipeline does NOT impose any heuristic — adapters MUST implement one.

5. **The `extra` dict on `BackfillItem` is adapter-private.** The runner never reads it (with one well-defined exception: `extra["_skip_reason"]`, which the runner consumes to populate `JobReport.skipped`). Adapters can stash anything else they need for `filter()` here without polluting the contract.

6. **CLI command name pattern is `breadmind kb backfill <source> ...`.** Sister specs should claim `notion`, `confluence`, `redmine` subcommands respectively; do not invent alternative verbs. Concrete class names follow `<Source>BackfillAdapter` (e.g. `NotionBackfillAdapter`).

7. **`parent_ref` is 1st-class, not optional metadata.** Any adapter with a parent/child relationship (Slack thread reply → message; Redmine journal → issue; Notion subpage → parent) MUST set it on the child item. The retrieval-time parent/child boost (follow-up spec) reads from this column directly. Use `f"{parent_source_kind}:{parent_native_id}"`.

8. **Two timestamps are 1st-class: `source_created_at` + `source_updated_at`.** Use `source_updated_at` as the range-filter axis (window is `since <= source_updated_at < until`, half-open); use `source_created_at` for retrieval-time recency weighting (follow-up spec). For sources without an "updated" concept, set both to the same value.

9. **Range filtering is the adapter's job.** Yield only items in `[since, until)` on `source_updated_at`. Use server-side filters where supported (Slack `oldest`/`latest`, Notion `last_edited_time`, Confluence CQL `lastmodified`, Redmine `updated_on`); otherwise client-side cut. Pipeline does NO post-yield cut.

10. **`cursor_of(item)` defines the opaque resume token.** `JobReport.cursor` and `kb_backfill_jobs.last_cursor` are stored verbatim, never parsed by the pipeline. Sisters MAY override the default (`source_native_id`) — Slack does, with `f"{ts_ms}:{channel_id}:{message_ts}"` for monotonic resume.

11. **`instance_id_of(source_filter)` is required.** Returns the workspace/instance identifier (Slack `team_id`, Notion `workspace_id`, Confluence base-URL host, Redmine base-URL hash) that keys `HourlyPageBudget` to `(org_id, instance_id)`. Without this, two orgs sharing one workspace, or one org spanning two workspaces, would merge their rate-limit budgets.

12. **`JobReport.skipped` is `dict[str, int]`, not `int`.** Total dropped == `sum(skipped.values())`. Each adapter publishes its own reason-key set in its concrete spec section (Slack's set is in §6.4); the runner contributes `"skipped_existing"`, `"redact_dropped"`, `"acl_lock"`, and `"archived"` universally.
