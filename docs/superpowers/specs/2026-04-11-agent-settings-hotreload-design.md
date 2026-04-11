# Agent Settings Hot-Reload Skill Design

**Date:** 2026-04-11
**Status:** Approved, ready for planning
**Branch:** refactor/code-quality-improvements

## Goal

Add built-in agent tools that let BreadMind's CoreAgent directly read and modify
its own runtime settings, with changes taking effect immediately (hot reload)
wherever possible — no process restart required.

This moves BreadMind closer to the "fully delegated general-purpose agent"
vision: when the user says "switch the LLM to Gemini" or "add this MCP server
and turn on its auto-discover", the agent can carry out the full operation
end-to-end instead of handing control back to the UI.

## Architecture

```
LLM (CoreAgent loop)
     │ tool_call
     ▼
breadmind_*_setting tools       (thin @tool wrappers)
     │
     ▼
SettingsService                 (new facade: validate → authorize → store → audit → emit)
     │
     ├─ FileSettingsStore / CredentialVault
     │
     └─ EventBus.emit(SETTINGS_CHANGED)
                  │
                  ▼
        SettingsReloadRegistry  (new: key_pattern → reload_fn)
                  │
                  ▼
  LLMProvider / Persona / SafetyGuard / Monitoring / Limits / ...
          (each component owns its own reload_fn)
```

**Core principles:**

1. **SettingsService is a facade** that extracts the existing per-kind logic from
   `ActionHandler._settings_write/_append/_update_item/_credential_store/
   _credential_delete`. The existing `ActionHandler` is refactored to delegate
   into it so UI and tool paths share one validation/audit/event pipeline.

2. **SettingsReloadRegistry is independent**. Each component registers a
   `(key_pattern, async reload_fn)` pair at initialization time. Hot-reload
   logic lives inside the component that owns the state, not in a central
   switch.

3. **Agent tools are behaviourless**. They do JSON parsing, parameter shaping,
   and result formatting only. All business logic goes through SettingsService.

4. **Full hot-reload coverage**. Every hot-reloadable key listed in
   `settings_schema.py` gets a subscriber wired up in this PR. Only
   `embedding_config` remains `requires_restart=true`.

5. **Security at the facade entry point**. Authorization, approval gating, and
   rate limiting are enforced in `SettingsService` so every caller path
   (agent tool, UI form, future programmatic caller) gets the same guarantees.

## Components

### New modules

| File | Responsibility |
|---|---|
| `src/breadmind/settings/service.py` | `SettingsService` — facade for validate/authorize/store/audit/emit. Methods: `get`, `set`, `append`, `update_item`, `delete_item`, `list_credentials`, `set_credential`, `delete_credential`. |
| `src/breadmind/settings/reload_registry.py` | `SettingsReloadRegistry` — `register(key_pattern, reload_fn)` / `dispatch(event)`. Supports exact keys and prefix globs like `apikey:*`. |
| `src/breadmind/tools/settings_tools.py` | 8 `@tool` functions wrapping the facade. |
| `src/breadmind/tools/settings_tool_registration.py` | Thin entry point that instantiates `SettingsService` + registers the tools into `ToolRegistry` at CoreAgent init. |

### Modified modules

| File | Change |
|---|---|
| `src/breadmind/core/events.py` | Add `EventType.SETTINGS_CHANGED`. |
| `src/breadmind/sdui/actions.py` | `_settings_write / _settings_append / _settings_update_item / _credential_store / _credential_delete` delegate into `SettingsService`. Existing public signatures, bootstrap exception for `safety_permissions_admin_users`, and audit entries remain byte-compatible so that all 542 existing SDUI tests stay green. |
| `src/breadmind/llm/factory.py` or the CoreAgent provider holder | Introduce a `LLMProviderHolder` that the agent loop reads through. A reloader subscribes to `llm` and `apikey:*` and calls `holder.swap(create_provider(new_config))`. |
| Persona loader | Subscribes to `persona`, `custom_prompts`, `custom_instructions`; invalidates internal cache on event. |
| `src/breadmind/core/safety_guard.py` | Subscribes to `safety_blacklist`, `safety_approval`, `safety_permissions_*`, `tool_security`; reloads rules in place. |
| Monitoring module | Subscribes to `monitoring_config`, `loop_protector`, `scheduler_cron`, `webhook_endpoints`. |
| Core agent init | Subscribes for `retry_config`, `limits_config`, `polling_config`, `agent_timeouts`, `system_timeouts`, `logging_config`, `memory_gc_config`. |
| `src/breadmind/mcp/server_manager.py` | Subscribes to `mcp`, `mcp_servers` and triggers its existing restart path. |
| Plugin manager | Subscribes to `skill_markets`. |

Component-internal reloaders may require exact file paths to be confirmed
during planning — the implementer should grep for current consumers of each
key and wire the subscriber into the most natural owner. The design requires
that *every* hot-reloadable key has exactly one subscriber by the end of the
work.

### Tools (final surface: 8)

All tools are async and return a human-readable status string. Values are
passed as JSON-encoded strings so the LLM can express scalars, lists, and
dicts through a single parameter without requiring OpenAPI variant types.

```python
@tool(description="Read a BreadMind runtime setting. Credentials are masked.",
      read_only=True, concurrency_safe=True)
async def breadmind_get_setting(key: str) -> str: ...

@tool(description="Search the settings catalogue. Returns key, label, tab, field_id for matches.",
      read_only=True, concurrency_safe=True)
async def breadmind_list_settings(query: str = "", tab: str = "") -> str: ...

@tool(description="Overwrite a BreadMind runtime setting. Use for scalars and dict/list replacement. Triggers hot reload when applicable.")
async def breadmind_set_setting(key: str, value: str) -> str: ...

@tool(description="Append an item to a list-valued setting (e.g. mcp_servers, skill_markets).")
async def breadmind_append_setting(key: str, item: str) -> str: ...

@tool(description="Update a specific item in a list-valued setting by matching one field.")
async def breadmind_update_setting_item(key: str, match_field: str, match_value: str, patch: str) -> str: ...

@tool(description="Delete a specific item from a list-valued setting by matching one field.")
async def breadmind_delete_setting_item(key: str, match_field: str, match_value: str) -> str: ...

@tool(description="Store a secret credential (e.g. apikey:anthropic, vault:ssh:prod). Requires approval.")
async def breadmind_set_credential(key: str, value: str, description: str = "") -> str: ...

@tool(description="Delete a stored credential.")
async def breadmind_delete_credential(key: str) -> str: ...
```

**Success format:**
```
OK. key=llm, operation=set, hot_reloaded=true, restart_required=false, audit_id=1234
```

**Failure format:**
```
ERROR: validation failed — llm.default_provider must be one of [claude,gemini,grok,ollama,cli]
```

**Approval format:**
```
PENDING: approval required for key=apikey:anthropic. approval_id=approve-47. Ask the user to confirm.
```

## Data Flow

Example: agent changes the LLM provider.

```
1. Tool call
   breadmind_set_setting(key="llm",
                         value='{"default_provider":"gemini","default_model":"gemini-2.0-flash"}')

2. Tool function: JSON parse → SettingsService.set(key, parsed, actor="agent:core")

3. SettingsService.set:
   a. is_allowed_key("llm") → True
   b. _authorize(key, actor) → not admin/credential, pass
   c. validate_value("llm", parsed) → ok
   d. old = await store.get_setting("llm")
   e. await store.set_setting("llm", parsed)
   f. await audit.record("settings_write", key, actor, old_hash, new_hash, ...)
   g. dispatch_result = await registry.dispatch(SETTINGS_CHANGED event)
   h. await event_bus.emit(SETTINGS_CHANGED, payload)
   i. return SetResult(ok=True, hot_reloaded=dispatch_result.all_ok,
                       restart_required=False, reload_errors=dispatch_result.errors)

4. Registry dispatch (in step 3g):
   a. Find reload_fns matching "llm" → [LLMProviderReloader.reload]
   b. Run via asyncio.gather(..., return_exceptions=True)
   c. LLMProviderReloader.reload(new):
      - new_provider = create_provider(new)   # may raise
      - holder.swap(new_provider)
   d. Collect success/failure list, return DispatchResult

5. Tool returns:
   "OK. key=llm, operation=set, hot_reloaded=true, restart_required=false, audit_id=1234"

6. Next CoreAgent turn:
   holder.current() returns the new provider → change is already live
```

### Event payload schema

```python
SETTINGS_CHANGED = {
    "key": str,                 # "llm" or "apikey:anthropic"
    "operation": str,           # set | append | update_item | delete_item | credential_store | credential_delete
    "old": Any | None,          # None for credential keys (no plaintext in events)
    "new": Any | None,          # None for credential keys
    "actor": str,               # "agent:core" | "user:alice" | "system"
    "audit_id": int,
}
```

Credential events carry no plaintext; subscribers that need the secret must
re-read from `CredentialVault` themselves.

### Concurrency

- Per-key `asyncio.Lock` inside `SettingsService` serializes writes to the same
  key. Different keys run in parallel.
- `registry.dispatch` runs reloaders via `asyncio.gather(..., return_exceptions=True)`.
  One failing subscriber never blocks the others.

## Failure Modes

| Failure | Behaviour | Recovery |
|---|---|---|
| Validation error | Write + event skipped | Agent retries with corrected value |
| Store I/O error | Write rolled back, no event | Agent retries or surfaces to user |
| Single reloader raises | Store change kept, audit records `reload_error`, other reloaders still run | Tool result has `hot_reloaded=false` — agent decides whether to roll back |
| All reloaders fail | Store change kept | Tool result advises restart |
| Approval times out | Pending record expires, write never happens | Agent re-requests |
| Rate limit exceeded | Write rejected | Agent retries after window |

**Atomicity rule:** the store write is the commit point. Once it succeeds,
the change is persisted even if hot-reload dispatch fails. This matches
current BreadMind behaviour (which already persists through a restart) and
avoids the worse alternative of having the store and the running process
disagree for subtle reasons.

## Security & Authorization

### Key classification

| Class | Examples | Agent-actor policy |
|---|---|---|
| **Safe** | `monitoring_config`, `logging_config`, `retry_config`, `limits_config`, `polling_config`, `agent_timeouts`, `system_timeouts`, `memory_gc_config`, `persona`, `custom_prompts`, `custom_instructions` | Direct write, audit recorded |
| **Sensitive** | `llm`, `mcp`, `mcp_servers`, `skill_markets`, `scheduler_cron`, `webhook_endpoints`, `embedding_config`, `tool_security` | Direct write, audit records old/new diff |
| **Admin-only** | `safety_blacklist`, `safety_approval`, `safety_permissions_admin_users`, `safety_permissions_*` | SafetyGuard approval required; pending ID returned |
| **Credential** | `apikey:*`, `vault:*` | SafetyGuard approval required; plaintext masked in audit and never carried in events |

### Actor model

- Agent tool calls set `actor="agent:<agent_id>"`.
- Existing UI calls continue with `actor="user:<user_id>"`.
- The `safety_permissions_admin_users` bootstrap exception (allowing append
  when the admin list is empty) applies **only to `user:*` actors**. An agent
  can never nominate itself or anyone else as the first admin.

### Approval flow

Reuses BreadMind's existing SafetyGuard approval pattern. When an admin-only
or credential write is requested by an agent actor:

1. SettingsService creates an approval record (purpose, key, value hash, actor).
2. Returns `PendingApproval(id=...)` to the caller.
3. Tool turns this into `PENDING: approval required ... approval_id=<id>`.
4. The agent asks the user to confirm.
5. On user approval (existing CLI/UI path), the approval resolver calls back
   into SettingsService with the stored arguments to perform the actual write.

If the existing approval API does not already expose a deferred-execution
callback, the planning phase must add a minimal in-memory pending queue
with `/approve <id>` hook.

### Audit log

Reuse the existing `_record_audit` helper with added fields:

```python
{
    "kind": "settings_write" | "settings_append" | "settings_update_item"
          | "credential_store" | "credential_delete",
    "key": str,
    "actor": str,
    "old_hash": str,           # sha256 (credential: hash of plaintext)
    "new_hash": str,
    "old_preview": dict | None,  # non-credential only
    "new_preview": dict | None,  # non-credential only
    "hot_reloaded": bool,
    "reload_error": str | None,
    "approval_id": str | None,
    "timestamp": datetime,
}
```

The existing 200-entry FIFO cap and the `_audit_log_card` UI viewer remain
unchanged.

### Rate limiting

SettingsService maintains a per-actor sliding window: default 20 writes/minute
for `agent:*` actors. User actors are exempt. The limit itself is a tunable
(`settings_write_rate_limit`, admin-only classification so an agent cannot
raise it to escape the throttle).

## Testing Strategy

### Unit tests

| File | Scope |
|---|---|
| `tests/settings/test_settings_service.py` | Facade: validate, authorize, store/vault routing, key locks, rate limit, approval pending path, credential masking in events |
| `tests/settings/test_reload_registry.py` | Exact key + prefix glob matching, parallel dispatch, failure isolation |
| `tests/tools/test_settings_tools.py` | 8 tools: JSON parsing, error formatting, delegation (service mocked) |
| `tests/tools/test_settings_tools_e2e.py` | End-to-end with real FileSettingsStore + SettingsService + Registry; assert LLMProviderHolder swaps on `breadmind_set_setting("llm", ...)` |
| `tests/sdui/test_settings_actions_facade.py` | After ActionHandler refactor, the full existing SDUI suite (542 tests) stays green |

### Per-component reloader tests

For each subscriber added in the wiring step, a focused test:

- `test_llm_provider_reloader.py` — `holder.current()` differs before/after swap
- `test_persona_reloader.py` — cache invalidation reflects in next lookup
- `test_safety_guard_reloader.py` — new blacklist rule blocks matching command immediately
- `test_monitoring_reloader.py` — rule changes affect evaluation pipeline
- Remaining reloaders: mock-based tests confirming `reload_fn` is called with the new value and the component's internal state updates.

### Integration tests

- `breadmind_append_setting("mcp_servers", <server>)` causes the MCP manager to start the new server (observable via `server_manager.list_servers()`).
- Agent actor attempting `safety_blacklist` write returns `PENDING` and no audit write-row is emitted until approval resolves.
- Rate limit: 21st write within the same minute returns `ERROR: rate limit exceeded`.

## Implementation Slicing

The work decomposes into thin slices that each leave the test suite green:

1. **Event infra** — `EventType.SETTINGS_CHANGED`, `SettingsReloadRegistry` + its tests.
2. **Facade** — `SettingsService` (no rate limit, no approval yet) + unit tests.
3. **ActionHandler refactor** — delegate the 5 action kinds into `SettingsService`. Full SDUI suite must remain at 542 green.
4. **Event emission** — `SettingsService` emits `SETTINGS_CHANGED`. Registry has no subscribers yet; event simply flows.
5. **Tools** — 8 `@tool` functions, JSON parsing, unit tests, registration entry point, tool-level E2E with mocked service.
6. **Subscribers** — wired component-by-component in this order: LLM → persona → safety guard → monitoring → limits/retry/polling/timeouts/logging/memory_gc → MCP → skill_markets. Each has its own test.
7. **Approval integration** — admin-only + credential keys go through pending approval, with deferred execution.
8. **Rate limiting** — per-actor sliding window, last so the earlier slices do not have to work around it.

Each slice commits independently; planning phase will turn each into a
numbered task with full file paths, code, and commands.

## Out of Scope

- Changing the semantics of `requires_restart` (still just `embedding_config`).
- Rewriting SafetyGuard itself — the design uses the existing approval path.
- New UI surfaces; the existing settings page continues to work unchanged.
- Distributed/commander-worker replication of settings changes.
- Cross-process hot-reload (only the local process reloads).

## Open Questions for Planning

These are the specific lookups the implementer must do during planning:

1. Exact location of the existing SafetyGuard approval API — does it already
   expose a "deferred callback" primitive we can reuse, or do we need to add
   a minimal pending queue?
2. Who currently owns each hot-reloadable key at runtime? For most keys this
   is obvious from grep, but a few (e.g., `logging_config`, `polling_config`)
   may be spread across several modules. The planning step needs to pick one
   owner per key.
3. Whether a `LLMProviderHolder` indirection already exists in any form, or
   whether the core loop currently holds a direct `LLMProvider` instance
   that must be lifted into a holder as part of slice 6.
