# Browser Engine Layer Design (Sub-project 1 of 4)

## Goal

Upgrade BreadMind's browser control from a single-file 343-line tool to a modular, production-grade browser engine that surpasses OpenClaw's CDP-based browser control. This is sub-project 1 of 4 in the browser control overhaul:

1. **Browser Engine Layer** (this spec) — session management, advanced actions, network monitoring, accessibility tree
2. AI Vision Layer — screenshot + a11y tree + network context fed to LLM, natural language multi-step execution
3. Macro System — record/save/replay browser action sequences, cron integration
4. Web UI — session dashboard + CDP screencast live view

## Approach

**Hybrid Playwright + CDP**: Keep Playwright as the main driver for stability and auto-wait. Use Playwright's `CDPSession` to access Chrome DevTools Protocol directly for features Playwright doesn't expose natively (screencast, detailed network interception, accessibility tree, performance metrics).

**Layering**: Existing `browser.py` stays as the low-level driver with minimal changes (add CDPSession accessor). New modules are built on top, not as replacements.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│            BrowserEngine (browser_engine.py)          │
│   Unified entry point: create/get/close sessions     │
│   Exposes tool definitions for LLM tool-calling      │
├──────────┬─────────────┬──────────────┬──────────────┤
│ Session  │   Actions   │   Network    │    A11y      │
│ Manager  │   Handler   │   Monitor    │  Extractor   │
├──────────┴─────────────┴──────────────┴──────────────┤
│          browser.py (existing low-level driver)       │
│          Playwright API + CDPSession access           │
└─────────────────────────────────────────────────────┘
```

## Module Breakdown

### 1. browser.py Changes (Minimal)

Only add a `get_cdp_session()` helper and expose the context/page objects for the upper layer to use. No behavioral changes to existing 11 actions.

```python
async def get_cdp_session(page) -> CDPSession:
    """Get CDP session from a Playwright page for direct protocol access."""
    return await page.context.new_cdp_session(page)
```

### 2. browser_session.py — SessionManager

Manages multiple browser sessions with lifecycle control.

**Core concepts:**
- `BrowserSession`: Wraps a Playwright BrowserContext + pages + CDPSession. Has an `id`, `name`, `mode`, `persistent` flag, `created_at`, `last_active`.
- `SessionManager`: Dict of active sessions. Creates, retrieves, closes sessions. Runs idle cleanup.

**Session types:**
- `transient`: Auto-closed after idle timeout (default 5 minutes). For one-off tasks.
- `persistent`: Stays alive until explicitly closed. For recurring access to infrastructure dashboards.

**Multi-instance support:**
- Each session is an independent Playwright BrowserContext (shares one Browser instance for memory efficiency).
- Multiple tabs within a session share cookies/auth state.
- Different sessions can have different auth states (e.g., Proxmox admin vs Grafana viewer).

**Headless auto-detection:**
- Check `os.environ.get("DISPLAY")` on Linux, presence of GUI on Windows/macOS.
- Config override: `browser.headless = true/false/auto` (default: auto).

**Idle cleanup:**
- Background asyncio task runs every 60 seconds.
- Closes transient sessions idle > timeout.
- Persistent sessions are never auto-closed.

**Concurrency limits:**
- Max 5 concurrent sessions (configurable).
- Max 10 tabs per session.

### 3. browser_actions.py — ActionsHandler

Extends browser capabilities beyond the existing 11 actions. All functions take a Playwright `Page` as first argument.

**New actions:**
- `hover(selector)` — Hover over element
- `drag_drop(source_selector, target_selector)` — Drag and drop
- `upload_file(selector, file_paths)` — File input handling via `set_input_files`
- `select_option(selector, value/label/index)` — Dropdown selection
- `scroll(direction, amount, selector?)` — Scroll page or element
- `get_cookies() / set_cookie(cookie_dict)` — Cookie management
- `get_storage(type)` — Read localStorage/sessionStorage
- `press_key(key, modifiers?)` — Keyboard input (Enter, Escape, Ctrl+A, etc.)
- `wait_for_navigation(url_pattern?, timeout?)` — Wait for navigation to complete
- `pdf(path?)` — Export page as PDF

### 4. browser_network.py — NetworkMonitor

Uses CDP `Network` and `Fetch` domains via `CDPSession`.

**Capabilities:**
- `start_capture(session_id, filters?)` — Begin capturing network traffic. Optional URL pattern filters.
- `stop_capture(session_id) -> list[RequestEntry]` — Stop and return captured entries.
- `block_urls(patterns)` — Block requests matching patterns (ads, analytics, large images).
- `intercept_request(url_pattern, handler)` — Modify requests before they're sent.
- `export_har(session_id) -> str` — Export captured traffic as HAR JSON.

**RequestEntry structure:**
```python
@dataclass
class RequestEntry:
    url: str
    method: str
    status: int
    request_headers: dict
    response_headers: dict
    body_size: int
    duration_ms: float
    resource_type: str  # document, script, image, xhr, fetch, etc.
    timestamp: float
```

**Design notes:**
- Capture is opt-in (not always on) to minimize overhead.
- Body content is NOT captured by default (memory concern). Optional `include_body=True` for specific URL patterns.
- Max 1000 entries per capture session, oldest evicted.

### 5. browser_a11y.py — A11yExtractor

Uses CDP `Accessibility.getFullAXTree` to extract the accessibility tree.

**Output format:**
Compact text format optimized for LLM token efficiency:

```
[button "Sign In" focused]
[input "Email" value=""]
[input "Password" value="" type=password]
[link "Forgot password?" href="/reset"]
[heading level=1 "Dashboard"]
[table "CPU Usage" rows=5 cols=3]
  [row: "Node-1", "45%", "OK"]
  [row: "Node-2", "89%", "Warning"]
```

**Features:**
- Filter by role (e.g., only interactive elements for action planning)
- Filter by subtree (a11y tree under a specific node)
- Include/exclude hidden elements
- Max depth control (default 10 levels)
- Estimated token count in metadata

### 6. browser_engine.py — BrowserEngine (Unified Entry Point)

Orchestrates all modules. Exposes tool definitions for the LLM.

**Tool definitions exposed:**

```python
# Session management
browser_session(action, name?, mode?, persistent?, ...)
# → create, list, close, close_all

# Browsing (operates on a named session)
browser_navigate(session, url, wait_until?)
browser_action(session, action, **params)
# → click, fill, hover, drag_drop, upload_file, select_option, scroll, press_key, ...

# Observation
browser_screenshot(session, full_page?, selector?)
browser_get_text(session, selector?)
browser_get_a11y_tree(session, filter?, max_depth?)

# Network (opt-in)
browser_network(session, action, **params)
# → start_capture, stop_capture, block_urls, export_har

# Lifecycle
browser_close(session?)
```

**Session resolution:**
- If `session` param is omitted, use the most recently active session.
- If no session exists, auto-create a transient one.
- This preserves backward compatibility — existing `browser(action="navigate", url="...")` still works.

## Config

Add to `config.py`:

```python
@dataclass
class BrowserConfig:
    headless: str = "auto"           # "auto" | "true" | "false"
    max_sessions: int = 5
    max_tabs_per_session: int = 10
    idle_timeout_seconds: int = 300  # 5 minutes for transient sessions
    default_timeout_ms: int = 10000
    viewport_width: int = 1280
    viewport_height: int = 900
    locale: str = "ko-KR"
```

## File Plan

| File | Action | Responsibility |
|------|--------|----------------|
| `src/breadmind/tools/browser.py` | Modify (minimal) | Add CDPSession helper, expose page/context |
| `src/breadmind/tools/browser_session.py` | Create | SessionManager, BrowserSession, idle cleanup |
| `src/breadmind/tools/browser_actions.py` | Create | Advanced actions (hover, drag, upload, etc.) |
| `src/breadmind/tools/browser_network.py` | Create | CDP Network/Fetch based capture and blocking |
| `src/breadmind/tools/browser_a11y.py` | Create | Accessibility tree extraction and formatting |
| `src/breadmind/tools/browser_engine.py` | Create | Unified BrowserEngine, tool definitions |
| `src/breadmind/config.py` | Modify | Add BrowserConfig dataclass |
| `src/breadmind/plugins/builtin/browser/plugin.py` | Modify | Wire BrowserEngine instead of raw browser tool |
| `tests/tools/test_browser_session.py` | Create | Session lifecycle tests |
| `tests/tools/test_browser_actions.py` | Create | Action handler tests |
| `tests/tools/test_browser_network.py` | Create | Network monitor tests |
| `tests/tools/test_browser_a11y.py` | Create | A11y extraction tests |
| `tests/tools/test_browser_engine.py` | Create | Integration tests |

## Backward Compatibility

The existing `browser()` function stays functional. `BrowserEngine` wraps it — if the engine is available, it's used; otherwise the old single-session tool works as before. The plugin switches to exposing BrowserEngine tools but the old tool name remains as an alias.

## What This Does NOT Cover

These are handled by subsequent sub-projects:
- AI Vision analysis of screenshots (Sub-project 2)
- Natural language multi-step browser commands (Sub-project 2)
- Macro recording/replay (Sub-project 3)
- Web UI session dashboard and live view (Sub-project 4)
