# Episodic Memory — Multi-tenancy Activation (Phase 2 v2 / UUID)

## 1. Overview

BreadMind's episodic memory is **single-tenant by default**. All Phase 1
deployments wrote `episodic_notes` rows with `org_id IS NULL`, and recall
matched every NULL-org note for every user.

Phase 2 v2 introduces **optional per-tenant isolation** via a UUID
`org_id` column on `episodic_notes`, FK to `org_projects(id)`. Behaviour
is fully backwards-compatible:

- Single-org deployments that never set `org_id` keep their existing NULL
  notes and continue to recall them — no UPDATE / backfill required.
- The matching SQL defaults to **permissive** mode: a UUID filter still
  pulls in NULL-org notes (`org_id IS NULL OR org_id = $n`) so legacy data
  is not orphaned during rollout.
- Strict isolation is opt-in via `BREADMIND_EPISODIC_STRICT_ORG=1` and
  should only be flipped after a deliberate backfill (Section 3, Step 4).

This document is the operator-facing guide for activating multi-tenancy:
how to seed `org_projects`, how to map Slack workspaces, when to flip
strict mode, and how to backfill legacy NULL-org rows.

## 2. Architecture summary

| Component | Role |
|---|---|
| `org_projects` (migration `004_org_kb`) | UUID PK, `slack_team_id`, `name`. Source of truth for org identity (shared with `org_kb`). |
| `episodic_notes.org_id` (migration `009_episodic_org_id`) | `UUID REFERENCES org_projects(id) ON DELETE SET NULL`. NULL = legacy / single-tenant. |
| `breadmind.memory.runtime._resolve_org_id` | 4-step fallback: `explicit → ctx → BREADMIND_DEFAULT_ORG_ID → None`. Invalid UUIDs collapse to None with a WARN log. |
| `breadmind.memory.runtime._lookup_org_id_by_slack_team` | Async helper. Reads `org_projects.slack_team_id`, caches hits and misses in a process-local dict guarded by `asyncio.Lock`. |
| `breadmind.messenger.org_routing.dispatch_to_agent` | Resolves `IncomingMessage.tenant_native_id` (Slack `team_id`) → `org_id` and forwards to `CoreAgent.handle_message(..., org_id=...)`. |
| `EpisodicFilter.org_id` (`memory/episodic_store.py`) | When `None`, no org filter. When set, builds `(org_id IS NULL OR org_id = $n)` (permissive) or `org_id = $n` (strict — `BREADMIND_EPISODIC_STRICT_ORG=1`). |

Composite indexes provided by migration `009`:

- `ix_episodic_org_user_kind_recent (org_id, user_id, kind, created_at DESC)`
- `ix_episodic_org_tool_outcome (org_id, tool_name, outcome, created_at DESC) WHERE tool_name IS NOT NULL`

## 3. Activation procedure

### Step 1 — Seed `org_projects`

`org_projects` is created by migration `004_org_kb`. Insert one row per
tenant. The UUID generated here is the value that flows through
`episodic_notes.org_id`.

```sql
INSERT INTO org_projects (id, name, slack_team_id)
VALUES (gen_random_uuid(), 'Acme Corp', 'T01ABC234')
RETURNING id;
```

- `slack_team_id` is the Slack workspace ID (visible at
  https://api.slack.com/apps → **Basic Information**, or via `auth.test`
  on a bot token). The column is declared `TEXT NOT NULL` (migration
  `004_org_kb`), so non-Slack tenants must supply a placeholder string
  (e.g. `'<non-slack>'`) until a future migration relaxes nullability.
  Only rows whose value matches an inbound Slack `team_id` participate
  in the lookup path.
- The returned `id` UUID is what you set in `BREADMIND_DEFAULT_ORG_ID` if
  you want a deployment-wide fallback (see Section 4).

### Step 2 — Slack app installation → `team_id` mapping

The Slack gateway (`breadmind.messenger.slack.SlackGateway`) stamps every
inbound message with `IncomingMessage.tenant_native_id = event["team_id"]`.
The router-level helper `dispatch_to_agent` in
`breadmind.messenger.org_routing` resolves it to a UUID via
`_lookup_org_id_by_slack_team` and forwards to
`CoreAgent.handle_message(..., org_id=...)`.

Operational checklist when onboarding a Slack workspace:

1. Install the Slack app to the workspace (existing OAuth flow).
2. Capture the workspace `team_id` from the OAuth response or
   `slack_sdk.WebClient.auth_test()`.
3. Either INSERT a new `org_projects` row (Step 1) with that
   `slack_team_id`, or UPDATE the existing row:

   ```sql
   UPDATE org_projects SET slack_team_id = 'T01ABC234' WHERE id = '<uuid>';
   ```

4. Restart the BreadMind process **or** call
   `breadmind.memory.runtime.clear_org_lookup_cache()` from a maintenance
   shell — the lookup cache is process-local and only invalidates on
   process restart or explicit clear.

> **Miss handling.** If a message arrives from an unmapped `team_id`,
> `_lookup_org_id_by_slack_team` caches the miss (so the DB isn't hit
> repeatedly), increments
> `breadmind_org_id_lookup_total{outcome="miss"}`, and emits a single
> `WARNING` log per process per `team_id`. The agent call still proceeds
> with `org_id=None` (= legacy / fallback).

### Step 3 — Strict mode flip

Default = **permissive** (`BREADMIND_EPISODIC_STRICT_ORG=0` or unset).
A UUID-filtered search still recalls legacy NULL-org notes:

```sql
WHERE (org_id IS NULL OR org_id = $n)
```

This is intentional during rollout — single-tenant Phase 1 data continues
to be useful while you populate `org_id` on new writes.

Flip to **strict** (`BREADMIND_EPISODIC_STRICT_ORG=1`) only when **all**
of the following hold:

- All production `episodic_notes` rows have a non-NULL `org_id` (i.e.,
  Step 4 backfill has run and verified by row-count audit), **or** the
  remaining NULL-org rows are deliberately abandoned (e.g., dev-only
  Phase 1 data).
- `breadmind_org_id_lookup_total{outcome="miss"}` rate is near zero for
  Slack workspaces in active use (a sustained miss rate means new
  messages are still landing with `org_id=NULL` and would become
  invisible after the flip).
- You have taken a `pg_dump` of `episodic_notes` (Step 4 SAFETY note).

In strict mode the matching clause becomes:

```sql
WHERE org_id = $n
```

NULL-org rows remain in the table but are invisible to UUID-filtered
recall. They reappear if you flip back to permissive.

> Pre-flip audit query:
> ```sql
> SELECT count(*) FROM episodic_notes WHERE org_id IS NULL;
> ```
> Should be `0` for a clean strict cutover, or match a known set of
> abandonable rows.

### Step 4 — Legacy NULL-org backfill

Two strategies, depending on how the deployment grew.

**A. Single-org backfill** — your deployment was single-tenant and is
now adopting multi-tenancy with one primary org. Attribute all NULL-org
notes to that org:

```sql
BEGIN;
UPDATE episodic_notes
   SET org_id = '<the-one-org-uuid>'
 WHERE org_id IS NULL;
-- Verify expected row count, then:
COMMIT;
```

**B. Multi-org backfill** — multiple `org_projects` rows already exist
and you need to attribute existing NULL notes to the correct owner:

1. Identify owners by `user_id`. If users are 1:1 with orgs (e.g., via
   Slack workspace membership recorded in `org_project_members` or an
   external HRIS), JOIN through that mapping.
2. Run a batched UPDATE per org:

   ```sql
   UPDATE episodic_notes
      SET org_id = $1
    WHERE org_id IS NULL
      AND user_id = ANY($2::text[]);
   ```

3. Notes with ambiguous attribution can either be left NULL (visible to
   all orgs in permissive mode, invisible in strict mode) or DELETEd if
   they are abandonable.

> **SAFETY.** Take a `pg_dump` (or at minimum
> `pg_dump --table=episodic_notes`) before any backfill UPDATE. Once
> strict mode is flipped, recovering hidden NULL rows requires either a
> permissive flip-back or a DB restore — the column is unchanged but the
> recall surface is not. Reversibility is non-trivial after dependent
> agent state has been built on the new view.

## 4. Env var reference

| Env | Default | Effect |
|---|---|---|
| `BREADMIND_DEFAULT_ORG_ID` | (unset) | UUID fallback used when no explicit `org_id` is supplied per turn and the per-message Slack lookup did not hit. Invalid UUIDs are warn-logged and treated as unset. Read at call time, not at process start (`memory/runtime.py::_resolve_org_id`). |
| `BREADMIND_EPISODIC_STRICT_ORG` | `0` (off) | When `1`, `PostgresEpisodicStore.search` filters with `org_id = $n` and excludes legacy NULL-org notes from UUID-filtered recall. Truthy values: `1 / true / yes / on` (case-insensitive). |

Both knobs are read at call time, so changing the env var and restarting
the process is sufficient — no migration step is required.

## 5. Observability

| Metric | Type | Labels | Use |
|---|---|---|---|
| `breadmind_org_id_lookup_total` | Counter | `outcome={hit,miss}` | Slack `team_id` → `org_projects.id` resolution outcomes. Watch the miss rate during workspace onboarding — sustained misses indicate an unmapped `slack_team_id`. Required to be near zero before flipping strict mode (Step 3). |
| `breadmind_memory_recall_total` | Counter | `trigger={turn,tool}` | Already documented in `episodic-memory.md`. In multi-tenant deployments these recall calls are filtered by `org_id`; per-org dashboards are derivable from logs. |

Slack misses also emit a `WARNING` log line, deduped per process per
`team_id` (`logger.warning("Slack team_id %r not mapped to org_projects; "
"episodic notes will land with org_id=NULL", ...)`). Subsequent misses for
the same `team_id` are silent until `clear_org_lookup_cache()` runs.

## 6. Rollback

- **Strict-mode rollback.** Set `BREADMIND_EPISODIC_STRICT_ORG=0` (or
  unset) and restart. Permissive matching is restored immediately and
  legacy NULL-org notes are visible again. `episodic_notes.org_id`
  column values are unchanged.
- **Schema rollback.** `breadmind migrate downgrade 008_episodic_recorder`
  drops the `org_id` column and the two composite indexes added in `009`.
  **Data in `org_id` is lost on downgrade** — back up first if any
  multi-tenant writes have happened.
- **Lookup cache.** `breadmind.memory.runtime.clear_org_lookup_cache()`
  invalidates the in-memory `team_id → org_id` map and the warn-once
  set. Useful after `org_projects` UPDATEs or when re-running tests.

## 7. Known limitations / carry-over

- **Discord / Telegram / WhatsApp / Gmail / Signal gateways** — the
  `IncomingMessage.tenant_native_id` slot exists, but these gateways do
  not yet auto-populate it. Inbound messages fall through to
  `BREADMIND_DEFAULT_ORG_ID` (or `None`). Adding `discord_guild_id`,
  `telegram_chat_id`, etc. columns to `org_projects` is a follow-up
  spec.
- **Web / SDUI authentication** — there is no organization claim on web
  sessions yet. `CoreAgent.handle_message(org_id=...)` is not wired from
  the web routes, so web turns currently land with `org_id=None`.
  Multi-tenant web auth is a follow-up spec.
- **MCP / plugin spawn** — child agents spawned via MCP or the plugin
  system inherit the parent context's `org_id`; standalone MCP server
  spawns default to `org_id=None`.
- **Reflexion (`src/breadmind/core/reflexion.py`)** — currently records
  lessons with `org_id=None` (no propagation through the reflexion
  pipeline). Multi-tenant reflexion is a follow-up task; not blocking
  for the Phase 2 v2 rollout.
- **Single-loop process assumption.** `memory/runtime.py` constructs
  `_cache_lock = asyncio.Lock()` at module import; it lazy-binds to the
  first running event loop. Long-running processes that re-create their
  event loop (e.g. multiple `asyncio.run` calls in one process) will
  fail with `RuntimeError: <Lock> is bound to a different loop`. The
  production web/messenger stacks are single-loop; this is not a known
  issue in practice.
- **Gateway-side `on_message` wiring (lifecycle-spawned path).**
  `messenger/platforms.create_gateway()` instantiates gateways via
  `cls()` with no `on_message` callback (and no token args), so the
  `lifecycle.auto_start_all` path produces gateways whose inbound events
  are silently dropped before reaching `MessageRouter.handle_message`.
  The working production path is the explicit one in `main.py` and
  `cli/daemon.py`, which call `init_messenger(..., agent_handle_message
  =agent.handle_message)` and rely on `_make_route_handler` →
  `dispatch_to_agent` for org_id resolution. Closing the lifecycle gap
  (passing `on_message` into `create_gateway`) is a follow-up.
- **Approval-resume path drops `org_id`.**
  `CoreAgent.resume_after_approval` re-enters `handle_message` without
  threading the original turn's `org_id`; the resumed turn re-resolves
  via `_resolve_org_id(explicit=None, ctx_org_id=None)` and falls
  through to `BREADMIND_DEFAULT_ORG_ID` (or `None`). For multi-tenant
  approval flows, plumb `org_id` through the approval queue in a
  follow-up.

## 8. Cross-references

- Spec / plan: maintained in the project planning notes (gitignored;
  not checked into the repo). The canonical record of behavior lives
  in code; this document is the operator-facing summary.
- Phase 1 ops doc: [`episodic-memory.md`](./episodic-memory.md)
- Migration: `src/breadmind/storage/migrations/versions/009_episodic_org_id.py`
- Resolver: `src/breadmind/memory/runtime.py`
- Filter SQL: `src/breadmind/memory/episodic_store.py` (`PostgresEpisodicStore.search`)
- Slack dispatch: `src/breadmind/messenger/org_routing.py`
