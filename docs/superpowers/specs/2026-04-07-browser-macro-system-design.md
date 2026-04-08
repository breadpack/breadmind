# Browser Macro System Design (Sub-project 3 of 4)

## Goal

Enable recording, saving, and replaying browser action sequences as reusable macros. Integrate with the scheduler for cron-based automated execution (e.g., "take Grafana dashboard screenshots every morning").

## Architecture

```
┌──────────────────────────────────────────────┐
│        Macro Tools (browser_macro_tools.py)   │
│  LLM-callable: record, play, list, schedule  │
├──────────┬───────────────────────────────────┤
│ Recorder │         Executor                   │
│ Intercept│  Sequential step execution         │
│ actions  │  Error handling + screenshots      │
├──────────┴───────────────────────────────────┤
│       MacroStore (browser_macro_store.py)     │
│  In-memory dict + DB persistence via settings │
├──────────────────────────────────────────────┤
│       Data Models (browser_macro.py)          │
│  MacroStep, BrowserMacro dataclasses         │
└──────────────────────────────────────────────┘
```

## Module Breakdown

### 1. browser_macro.py — Data Models

**MacroStep:** Captures one browser action call.
```python
@dataclass
class MacroStep:
    tool: str        # "browser_navigate", "browser_action", etc.
    params: dict     # The tool call parameters
```

**BrowserMacro:** A named sequence of steps.
```python
@dataclass
class BrowserMacro:
    id: str
    name: str
    steps: list[MacroStep]
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
```

Both have `to_dict()` and `from_dict()` for serialization.

### 2. browser_macro_store.py — MacroStore

Follows the `WebhookAutomationStore` pattern:
- In-memory dict keyed by macro ID
- `save(db)` persists to settings table as `"browser_macros"` key
- `load(db)` restores on startup
- CRUD: `add`, `get`, `list_all`, `remove`, `update`

### 3. browser_macro_tools.py — Macro Tools for LLM

Exposes 4 tool functions:

| Tool | Description |
|------|-------------|
| `browser_macro_record` | Start/stop recording. While recording, intercepts all browser tool calls and saves them as macro steps. |
| `browser_macro_play` | Execute a saved macro by ID or name. Runs steps sequentially via BrowserEngine. |
| `browser_macro_list` | List all saved macros with metadata. |
| `browser_macro_manage` | Create/update/delete macros. Schedule a macro for cron execution. |

### Recording mechanism

When recording starts, a `MacroRecorder` wraps the BrowserEngine. It intercepts tool results from the engine and logs each call as a `MacroStep`. When recording stops, it returns the completed `BrowserMacro` and saves it to the store.

Implementation: The recorder doesn't replace the engine — it sits alongside and observes. The LLM continues using normal browser tools. The recorder hooks into the engine's action dispatch to capture what was called.

### Execution mechanism

`MacroExecutor` takes a macro and runs each step sequentially:
1. For each step, call the corresponding engine method
2. Optionally capture screenshot after each step
3. On error: stop and return partial results with error info
4. Update macro's last_executed timestamp

### Scheduler integration

`browser_macro_manage(action="schedule", macro_id="...", cron="0 9 * * 1-5")` creates a CronJob in the existing scheduler. The job's task is `"macro:{macro_id}"`. When the scheduler fires, it calls `MacroExecutor.execute()`.

## File Plan

| File | Action | Responsibility |
|------|--------|----------------|
| `src/breadmind/tools/browser_macro.py` | Create | MacroStep, BrowserMacro dataclasses |
| `src/breadmind/tools/browser_macro_store.py` | Create | In-memory store + DB persistence |
| `src/breadmind/tools/browser_macro_tools.py` | Create | 4 LLM-callable macro tools + recorder + executor |
| `src/breadmind/tools/browser_engine.py` | Modify | Add macro store reference, register macro tools |
| `src/breadmind/plugins/builtin/browser/plugin.py` | Modify | Initialize macro store, pass to engine |
| `tests/tools/test_browser_macro.py` | Create | Data model tests |
| `tests/tools/test_browser_macro_store.py` | Create | Store CRUD + persistence tests |
| `tests/tools/test_browser_macro_tools.py` | Create | Recording, playback, tool definition tests |
