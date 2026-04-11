# Dynamic Subagent Roles Design

## Goal

Remove all hardcoded subagent roles and the tier-based model selection system. Replace with a fully dynamic, DB-backed role registry where users and agents can create, modify, and delete subagent roles at runtime. Each role can specify its own LLM provider/model, tool access policy, and lifecycle (persistent vs transient).

## Architecture

The system centers on a single `RoleRegistry` that starts empty and loads persistent roles from a dedicated `subagent_roles` DB table. Transient roles live only in memory for the duration of a task. The `TierProviderPool` is removed; model selection is per-role.

## Data Model

### RoleDefinition

```python
@dataclass
class RoleDefinition:
    name: str                # Unique identifier (e.g. "my_k8s_expert")
    domain: str              # Domain (e.g. "k8s", "proxmox", "general")
    task_type: str           # Type (e.g. "diagnostician", "executor", "analyst")
    system_prompt: str       # Role-specific system prompt
    description: str = ""

    # Model selection (empty = use system default)
    provider: str = ""       # "claude", "gemini", "grok", "ollama", etc.
    model: str = ""          # "claude-sonnet-4-20250514", "gemini-2.0-flash", etc.

    # Tool access control
    tool_mode: str = "whitelist"   # "whitelist" | "blacklist"
    tools: list[str] = field(default_factory=list)

    # Lifecycle
    persistent: bool = True        # False = memory-only, auto-cleaned
    created_by: str = "user"       # "user" | "agent"

    # Execution limits
    max_turns: int = 5
```

### DB Table: `subagent_roles`

```sql
CREATE TABLE IF NOT EXISTS subagent_roles (
    name          TEXT PRIMARY KEY,
    domain        TEXT NOT NULL DEFAULT 'general',
    task_type     TEXT NOT NULL DEFAULT 'general',
    description   TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    tool_mode     TEXT NOT NULL DEFAULT 'whitelist',
    tools         JSONB NOT NULL DEFAULT '[]',
    max_turns     INTEGER NOT NULL DEFAULT 5,
    created_by    TEXT NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

Only `persistent=True` roles are written to this table. Transient roles exist in the RoleRegistry in-memory dict only.

## RoleRegistry Refactoring

### What changes

- Remove `_BUILTIN_ROLES` list entirely
- Remove `_COMMON_TOOLS` constant
- `__init__` starts with empty `_roles` dict
- Add async DB methods: `load_from_db()`, `save_to_db()`, `delete_from_db()`
- `register()` and `remove()` become async, accepting optional `db` parameter
- `get_tools()` returns `(tool_mode, tool_list)` tuple instead of flat list

### New methods

- `async load_from_db(db)` — Load all rows from `subagent_roles` into memory at startup
- `async register(role, db=None)` — Add to memory; if `persistent=True` and `db` provided, UPSERT to DB
- `async remove(name, db=None)` — Remove from memory; if in DB, DELETE from DB
- `cleanup_transient() -> list[str]` — Remove all `persistent=False` roles from memory, return removed names

### What is removed

- `_BUILTIN_ROLES` (9 hardcoded roles)
- `_COMMON_TOOLS` constant
- `TierProviderPool` class (`llm/tier_pool.py`)
- `LLMConfig.tier_low`, `tier_medium`, `tier_high` fields
- Bootstrap tier_pool initialization

## Model Selection

Each role optionally specifies `provider` and `model`. Resolution in the Orchestrator's subagent factory:

1. If `role.provider` is set: resolve to that provider instance (create/cache as needed), use `role.model` as override
2. If `role.provider` is empty: use the system default provider, no model override

Provider instances for non-default providers are cached to avoid redundant connections. The existing provider factory (`llm/factory.py`) handles instance creation.

## Tool Access Control

Each role specifies `tool_mode` and `tools`:

- **whitelist mode**: Only the listed tools are available to the subagent
- **blacklist mode**: All registered tools are available EXCEPT the listed ones

The Orchestrator's subagent factory resolves this:

```
all_tools = tool_registry.get_all_definitions()
if tool_mode == "whitelist":
    filtered = [t for t in all_tools if t.name in role.tools]
elif tool_mode == "blacklist":
    filtered = [t for t in all_tools if t.name not in role.tools]
```

## Agent-Created Roles

The `spawn_agent` tool is extended so the LLM can create roles dynamically:

- Add optional role definition parameters to `spawn_agent` (name, system_prompt, provider, model, tools, persistent)
- If role name doesn't exist, create it in RoleRegistry before spawning
- `persistent` parameter controls whether the role survives beyond the current task
- `created_by` is set to `"agent"` for agent-created roles

## Transient Role Lifecycle

- Created with `persistent=False`
- Stored in RoleRegistry memory only (never written to DB)
- Cleaned up via `cleanup_transient()` after Orchestrator task completion
- Agent can promote a transient role to persistent by re-registering with `persistent=True`

## API Endpoints

Reuse existing `/api/swarm/roles/*` paths, rewired to RoleRegistry + DB:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/swarm/roles` | List all roles (persistent + transient) |
| POST | `/api/swarm/roles` | Create role (name, system_prompt, provider, model, tool_mode, tools, persistent, ...) |
| PUT | `/api/swarm/roles/{name}` | Update role |
| DELETE | `/api/swarm/roles/{name}` | Delete role |

All endpoints write through RoleRegistry, which handles DB persistence for `persistent=True` roles.

## Bootstrap Changes

1. Create `RoleRegistry()` (empty)
2. Call `await role_registry.load_from_db(db)` to load persistent roles
3. Remove `TierProviderPool` creation
4. Pass `role_registry` to Orchestrator (no tier_pool parameter)
5. Remove `_persist_swarm_roles()` / `_restore_swarm_roles()` from `app.py` (replaced by RoleRegistry DB methods)

## Affected Files

| File | Change |
|------|--------|
| `core/role_registry.py` | Rewrite: remove hardcoded roles, add DB methods, new tool/model fields |
| `core/orchestrator.py` | Remove tier_pool usage, use role's provider/model directly |
| `core/subagent.py` | No change (already accepts provider + model_override) |
| `core/planner.py` | No change (already uses role_registry.list_role_summaries()) |
| `core/dag_executor.py` | Minor: call cleanup_transient() after execution |
| `llm/tier_pool.py` | Delete file |
| `config.py` | Remove tier_low/tier_medium/tier_high from LLMConfig |
| `core/bootstrap/__init__.py` | Remove tier_pool init, add load_from_db call |
| `storage/database.py` | Add subagent_roles table creation to schema init |
| `web/app.py` | Remove _persist_swarm_roles/_restore_swarm_roles |
| `web/routes/swarm.py` | Rewire role endpoints to RoleRegistry |
| `plugins/builtin/tools/spawn_tool.py` | Extend spawn_agent with role creation params |
