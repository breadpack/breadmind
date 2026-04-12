# Hooks v3: Extended Handlers & Conditional Filtering

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add 3 new hook handler types (PromptHook, AgentHook, HttpHook) and conditional filtering (`if`) to BreadMind's hook system, closing the gap with Claude Code's 5 handler types.

**Architecture:** Each new handler implements the existing `HookHandler` protocol (`run(payload) -> HookDecision`). Conditional filtering is applied at the `HookChain` level before dispatching to handlers. All handlers share the same decision protocol (proceed/block/modify/reply/reroute).

**Tech Stack:** Python 3.12+, aiohttp (HTTP hooks), Jinja2 (prompt templates), existing LLM provider system, existing ToolRegistry.

---

## 1. PromptHook — LLM-Based Hook

### Design

```python
@dataclass
class PromptHook:
    name: str
    event: HookEvent
    prompt: str              # Jinja2 template: {{ event }}, {{ data }}, {{ tool_name }}
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 15.0
    provider: str | None = None   # None = system default provider
    model: str | None = None      # None = auto-select lightweight model
    api_key: str | None = None    # For independent endpoint ($ENV_VAR interpolation)
    endpoint: str | None = None   # Independent endpoint URL
    if_condition: str | list[str] | None = None
```

### Behavior

1. Render `prompt` via Jinja2 with `{event, data, tool_name, args}` context
2. Call LLM (hybrid: existing provider system OR override via config)
3. Parse response as JSON `{"ok": true/false, "reason": "..."}`
4. `ok=false` on blockable event → BLOCK; on observational → log + PROCEED
5. `ok=true` → PROCEED with reason in context
6. Parse failure → `_failure_decision()` existing pattern

### LLM Resolution Order

1. If `endpoint` + `api_key` set → direct HTTP call (OpenAI-compatible API)
2. If `provider` + `model` set → `create_provider(provider).chat([...], model=model)`
3. If `model` only → system default provider with specified model
4. If nothing set → system default provider with cheapest/fastest model

### File

`src/breadmind/hooks/prompt_hook.py` (~120 lines)

---

## 2. AgentHook — Multi-Turn Agentic Verifier

### Design

```python
@dataclass
class AgentHook:
    name: str
    event: HookEvent
    prompt: str              # Verification instructions for the agent
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 30.0
    max_turns: int = 3
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | str = "readonly"
    if_condition: str | list[str] | None = None
```

### Behavior

1. Build system prompt: "You are a hook verifier. Use tools to check conditions. Respond with JSON `{ok, reason}`."
2. Run mini agent loop: prompt → LLM → tool calls → iterate (up to `max_turns`)
3. Tool access controlled by `allowed_tools`:
   - `"readonly"` preset: `["Read", "Grep", "Glob"]`
   - `"all"`: all registered tools
   - Explicit list: `["Read", "Grep", "Bash"]`
4. Extract JSON from final LLM response → same ok/reason protocol as PromptHook
5. If agent exhausts turns without JSON → PROCEED with warning

### Mini Agent Loop

Not a full CoreAgent — a standalone async function:
```
async def _run_agent_loop(prompt, provider, model, tools, max_turns, timeout) -> dict
```
- Uses LLM provider's chat() directly
- Tool calls filtered by whitelist before execution
- No memory, no EventBus emission (avoid infinite hook recursion)
- Returns `{"ok": bool, "reason": str}`

### File

`src/breadmind/hooks/agent_hook.py` (~180 lines)

---

## 3. HttpHook — Webhook Hook

### Design

```python
@dataclass
class HttpHook:
    name: str
    event: HookEvent
    url: str                 # POST target ($ENV_VAR interpolation)
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)  # $ENV_VAR interpolation
    method: str = "POST"     # POST | PUT
    if_condition: str | list[str] | None = None
```

### Behavior

1. Interpolate env vars in `url` and `headers` values (`$VAR` or `${VAR}`)
2. Validate URL against SSRF rules
3. POST/PUT JSON payload: `{"event": "...", "data": {...}, "hook_name": "..."}`
4. Parse response JSON using existing `_parse_shell_decision()` protocol:
   `{"action": "proceed|block|modify|reply|reroute", ...}`
5. Non-2xx status → `_failure_decision()`
6. Timeout/connection error → `_failure_decision()`

### SSRF Protection

Module: `src/breadmind/hooks/http_guard.py` (~60 lines)

- Block private IPs: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
- Block IPv6 loopback (::1) and link-local (fe80::/10)
- Block cloud metadata: 169.254.169.254, fd00:ec2::254
- HTTPS enforced by default (config: `allow_http: bool = False`)
- Optional `allowed_hosts: list[str]` — when set, strict mode (only listed hosts allowed)
- DNS resolution check: resolve hostname before connecting, verify resolved IP is not private

### File

`src/breadmind/hooks/http_hook.py` (~100 lines)
`src/breadmind/hooks/http_guard.py` (~60 lines)

---

## 4. Conditional Filtering (`if`)

### Syntax

Three pattern types, auto-detected:

| Pattern | Example | Matches |
|---|---|---|
| Tool pattern (CC compat) | `"Bash(git *)"` | tool_name=Bash, first arg matches `git *` |
| Data field match | `"data.channel_id=general"` | payload.data["channel_id"] == "general" |
| Event match | `"event=pre_tool_use"` | payload.event.value == "pre_tool_use" |

### Composition

- **OR**: array `["Bash(*)", "Write(*)"]` — any match passes
- **NOT**: prefix `!` — `"!Bash(rm *)"` means "NOT Bash with rm args"
- **Single string**: one condition

### Implementation

Module: `src/breadmind/hooks/condition.py` (~80 lines)

```python
def matches_condition(
    condition: str | list[str] | None,
    payload: HookPayload,
) -> bool:
    """Return True if hook should fire for this payload."""
```

- Tool pattern: regex `^(\w+)\((.+)\)$` → extract tool_name + arg glob
  - `tool_name` from `payload.data.get("tool_name")`
  - arg from `payload.data.get("tool_input")` or first arg string
  - Glob matching via `fnmatch`
- Data field: regex `^data\.(\w[\w.]+)=(.+)$` → nested dict lookup + string equality
- Event match: regex `^event=(.+)$` → compare to `payload.event.value`
- NOT: strip leading `!`, invert result

### Integration Point

`HookChain.run()` — before calling `handler.run(payload)`, check:
```python
if_cond = getattr(handler, "if_condition", None)
if if_cond is not None and not matches_condition(if_cond, payload):
    continue  # skip this handler
```

All 5 handler types (PythonHook, ShellHook, PromptHook, AgentHook, HttpHook) gain `if_condition` field.

---

## 5. Registry & DB Store Changes

### HookOverride.type expansion

Current: `"shell" | "python"`
New: `"shell" | "python" | "prompt" | "agent" | "http"`

### HookRegistry._build_from_override()

Add cases for `prompt`, `agent`, `http` types, reading type-specific config from `config_json`.

### DB store

No schema change — `config_json JSONB` already holds arbitrary config. New types just use different config keys:
- prompt: `{"prompt": "...", "provider": "gemini", "model": "gemini-2.5-flash"}`
- agent: `{"prompt": "...", "max_turns": 3, "allowed_tools": "readonly"}`
- http: `{"url": "https://...", "headers": {"Authorization": "Bearer $SECRET"}, "method": "POST"}`

### Web Routes

- `HookOverrideIn.type` validation: expand to accept `"prompt" | "agent" | "http"`
- SDUI hooks_view: add type options to form dropdown

---

## 6. Testing Strategy

- **PromptHook**: Mock LLM provider, test ok/false/parse-failure/timeout paths
- **AgentHook**: Mock LLM + mock tool registry, test multi-turn loop, tool filtering, max_turns exhaustion
- **HttpHook**: Mock aiohttp responses, test decision parsing, SSRF blocking, env var interpolation
- **http_guard**: Test all private IP ranges, HTTPS enforcement, allowed_hosts strict mode, DNS resolution
- **condition**: Test all 3 pattern types, OR composition, NOT prefix, edge cases (missing data fields)
- **Integration**: End-to-end with HookChain + conditional filtering + each handler type
- **DB round-trip**: Insert/read each new type via HookOverrideStore

Estimated: ~80 new tests across 6 test files.

---

## 7. File Map

| File | Action | Purpose |
|---|---|---|
| `src/breadmind/hooks/prompt_hook.py` | Create | PromptHook handler |
| `src/breadmind/hooks/agent_hook.py` | Create | AgentHook handler |
| `src/breadmind/hooks/http_hook.py` | Create | HttpHook handler |
| `src/breadmind/hooks/http_guard.py` | Create | SSRF protection module |
| `src/breadmind/hooks/condition.py` | Create | Conditional filtering engine |
| `src/breadmind/hooks/handler.py` | Modify | Add if_condition to PythonHook/ShellHook |
| `src/breadmind/hooks/chain.py` | Modify | Integrate condition check before handler.run() |
| `src/breadmind/hooks/registry.py` | Modify | Build prompt/agent/http from DB overrides |
| `src/breadmind/hooks/manifest.py` | Modify | Parse new types from plugin manifest |
| `src/breadmind/hooks/__init__.py` | Modify | Export new types |
| `src/breadmind/hooks/db_store.py` | No change | config_json already flexible |
| `src/breadmind/web/routes/hooks.py` | Modify | Accept new types in validation |
| `src/breadmind/sdui/views/hooks_view.py` | Modify | Add type options to form |
| `tests/hooks/test_prompt_hook.py` | Create | PromptHook tests |
| `tests/hooks/test_agent_hook.py` | Create | AgentHook tests |
| `tests/hooks/test_http_hook.py` | Create | HttpHook tests |
| `tests/hooks/test_http_guard.py` | Create | SSRF guard tests |
| `tests/hooks/test_condition.py` | Create | Condition filtering tests |
| `tests/hooks/test_chain_condition.py` | Create | Chain + condition integration |

---

## 8. Known Gaps / Future Work

- AgentHook `"all"` tools preset needs safety review (could enable shell execution in hooks)
- PromptHook Jinja2 sandbox (restrict template capabilities)
- HttpHook retry/backoff (not in scope — single attempt with timeout)
- Condition `AND` operator (intentionally excluded for simplicity)
- SDUI form dynamic fields per hook type (Phase 2 — current form is flat)
