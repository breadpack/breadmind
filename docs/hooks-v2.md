# Hooks v2 — Plugin Hook Authoring Guide

This document describes how to write hooks that intercept BreadMind events.
For design rationale see `docs/superpowers/specs/2026-04-12-hooks-v2-design.md`.

## Event catalog

See `src/breadmind/hooks/events.py` for the full `HookEvent` enum. Each
event has an `EventPolicy` entry controlling whether hooks may block,
modify payloads, return replies, or reroute calls.

Claude Code compatible events: `session_start`, `session_end`,
`user_prompt_submit`, `pre_tool_use`, `post_tool_use`, `stop`,
`subagent_stop`, `notification`, `pre_compact`.

BreadMind native events: `messenger_received`, `messenger_sending`,
`safety_guard_triggered`, `worker_dispatched`, `worker_completed`,
`llm_request`, `llm_response`, `memory_written`, `plugin_loaded`,
`plugin_unloaded`, `credential_accessed`.

## Declaring hooks in a plugin manifest

Add a `hooks` array to your plugin's `plugin.json`:

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "hooks": [
    {
      "name": "my-plugin:block-rm-rf",
      "event": "pre_tool_use",
      "type": "shell",
      "tool_pattern": "shell_*",
      "command": "python -c \"import json,sys; d=json.load(sys.stdin); sys.exit(1 if 'rm -rf /' in d['data'].get('args',{}).get('cmd','') else 0)\"",
      "priority": 100
    },
    {
      "name": "my-plugin:inject-namespace",
      "event": "pre_tool_use",
      "type": "python",
      "entry": "my_plugin.hooks:inject_namespace",
      "priority": 50
    }
  ]
}
```

## Python hook entry point

```python
from breadmind.hooks import HookDecision, HookPayload

def inject_namespace(payload: HookPayload) -> HookDecision:
    args = payload.data.get("args", {})
    if "namespace" not in args:
        args = {**args, "namespace": "default"}
        return HookDecision.modify(args=args)
    return HookDecision.proceed()
```

## Shell hook stdin/stdout protocol

Input on stdin (JSON):
```json
{"event": "pre_tool_use", "data": {"tool_name": "shell_exec", "args": {"cmd": "ls"}}}
```

Output on stdout (JSON or empty):
- Empty → proceed
- `{"action": "proceed", "context": "..."}`
- `{"action": "block", "reason": "..."}`
- `{"action": "modify", "patch": {"args": {...}}}`
- `{"action": "reply", "result": "..."}`
- `{"action": "reroute", "target": "other_tool", "args": {...}}`

Non-zero exit code on blockable events = block with stderr as reason.

## Reroute loop protection

Reroute decisions are bounded by:
- Maximum depth of 3 (see `MAX_REROUTE_DEPTH` in `chain.py`).
- Visited target set — a target in `payload.visited` will not be routed to again.

## DB overlays

User-level enable/disable and priority adjustments can be stored in the
`hook_overrides` table and edited via the web UI (Phase 3, separate spec).
New Python hooks cannot be added via DB in Phase 1 — they must come from
a plugin manifest. Shell hooks can be added DB-only.

## Legacy adapters

Existing `ToolHookRunner`, `LifecycleHookRunner`, and the safety
`HookRunner` continue to work. They delegate internally to `HookChain`,
so migrating your code is not required for Phase 1.

## Phase 2 status (2026-04-12)

Events actively wired in BreadMind publishers:

| Event | Publisher | Location | Notes |
|---|---|---|---|
| `session_start` / `user_prompt_submit` / `stop` | `core/agent.py` | `CoreAgent.handle_message` | Phase 1 Task 15 |
| `pre_tool_use` / `post_tool_use` | `core/tool_hooks.py` (legacy adapter) + `core/tool_executor.py`, `tools/registry.py` | existing call sites delegate to new chain |
| `pre_compact` | `memory/compressor.py` | `compress_history` entry | block skips compaction, modify replaces messages |
| `llm_request` / `llm_response` | `llm/base.py` | `chat_with_hooks` helper | Concrete providers (claude/gemini/grok/ollama/cli) do NOT yet call the helper — adoption is a follow-up |
| `messenger_received` | `messenger/router.py` | `MessengerGateway._on_message` wrapper set in `__init__` | All in-tree gateways flow through the wrapper via `super().__init__` |
| `messenger_sending` | — | — | Deferred: no single chokepoint identified in Phase 2 |
| `safety_guard_triggered` | `core/agent.py` | `_emit_safety_triggered` helper | **Helper exists and is tested, but caller wiring lives in `ToolExecutor` — full wiring deferred to a follow-up PR** |
| `plugin_loaded` / `plugin_unloaded` | `plugins/manager.py` | `load_from_directory`, `unload` | success-only |
| `memory_written` | `memory/semantic.py`, `memory/episodic.py` | `add_entity`, `add_relation`, `add_note` | Phase 2 wires only these three; working/profiler layers deferred |
| `worker_dispatched` / `worker_completed` | `network/commander.py` | `dispatch_task`, `_handle_task_result` | Distributed mode only |
| `credential_accessed` | `storage/credential_vault.py` | `CredentialVault.retrieve` | Fires only on successful decrypt |
| `subagent_stop` / `notification` | — | — | Deferred: no active publishers in Phase 1/2; will be wired when subagent runtime matures |

### Known follow-ups

1. **Concrete LLM provider adoption**: `chat_with_hooks` helper exists in `llm/base.py` but `claude.py`, `gemini.py`, `grok.py`, `ollama.py`, and `cli.py` still call their `_chat_impl` paths directly. Each provider needs a one-line switch to route through the helper.
2. **ToolExecutor safety wiring**: `CoreAgent._emit_safety_triggered` is tested and ready, but `SafetyGuard.check()` is invoked inside `ToolExecutor` (not `CoreAgent.handle_message`). A small follow-up PR should thread the emit through `ToolExecutor`.
3. **CoreAgent STOP early-return paths**: `handle_message` has ~10 early-return sites where STOP is not currently emitted. A try/finally refactor would unify the emit point.
4. **`messenger_sending`**: needs a common send chokepoint — consider adding a `MessengerGateway.send` base method and routing all gateways through it.
5. **`HookDecision.reply` field naming collision**: Phase 1 Task 1 uses a post-class classmethod attachment workaround. Cleanup: rename the field to `reply_value` and adjust the one test + chain accumulation path.
6. **Phase 3 / Phase 4 specs**: `hooks-skills-observability` (web UI editor + trace) and `skills-v2` (structured skill bundles) remain outstanding.
