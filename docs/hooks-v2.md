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
