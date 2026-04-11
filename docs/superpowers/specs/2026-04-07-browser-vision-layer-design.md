# Browser AI Vision Layer Design (Sub-project 2 of 4)

## Goal

Enable BreadMind's browser engine to "see" and "understand" web pages by feeding screenshots + accessibility trees to the LLM Vision API, and support natural language multi-step browser commands.

## Current State

- Browser engine captures screenshots with `[screenshot_base64]...[/screenshot_base64]` tags
- `LLMMessage.attachments` field already supports `Attachment(type="image", data=base64, media_type="image/png")`
- Claude and Gemini providers already convert attachments to their respective image formats
- **Gap**: No code extracts screenshot tags from tool results into Attachment objects — the LLM never actually sees the images

## Architecture

```
┌─────────────────────────────────────────────────┐
│          VisionBrowser (browser_vision.py)        │
│  High-level API: "Go to Grafana, screenshot CPU" │
│  Multi-step planner + vision feedback loop        │
├─────────────────────────────────────────────────┤
│       PageAnalyzer (browser_page_analyzer.py)    │
│  Screenshot + A11y Tree → LLM → page description │
│  Element identification by natural language       │
├─────────────────────────────────────────────────┤
│    ScreenshotProcessor (browser_screenshot.py)   │
│  Extract [screenshot_base64] from tool results   │
│  Convert to Attachment objects                    │
│  Hook into ToolExecutor pipeline                 │
├─────────────────────────────────────────────────┤
│         BrowserEngine (existing)                  │
│  Sessions, actions, network, a11y tree           │
└─────────────────────────────────────────────────┘
```

## Module Breakdown

### 1. browser_screenshot.py — ScreenshotProcessor

Parses `[screenshot_base64]...[/screenshot_base64]` tags from tool result strings, converts them to `Attachment` objects, and strips the raw base64 from the text content (to avoid sending the same image data twice — once as text, once as image).

```python
def process_tool_result(content: str) -> tuple[str, list[Attachment]]:
    """Extract screenshot tags from tool result, return cleaned text + attachments."""
```

Also integrates with `ToolExecutor` via a post-processing hook: after any browser tool returns, process its output to extract images.

### 2. browser_page_analyzer.py — PageAnalyzer

Combines screenshot + accessibility tree into a structured page analysis request to the LLM.

```python
class PageAnalyzer:
    async def analyze_page(session, question: str = "") -> str:
        """Capture screenshot + a11y tree, send to LLM, return analysis."""

    async def find_element(session, description: str) -> str:
        """Find element matching natural language description, return selector."""
```

- `analyze_page`: Takes a screenshot, extracts a11y tree, builds a prompt with both, sends to the LLM with vision, returns the LLM's analysis as text.
- `find_element`: Specialized version that asks the LLM to identify a specific element and return a CSS selector or a11y-based identifier for it.

Uses a compact prompt template that includes:
- The screenshot as an image attachment
- The a11y tree (interactive elements only for token efficiency)
- The user's question or element description
- Network context summary (if capture is active, optional)

### 3. browser_vision.py — VisionBrowser (High-Level Tool)

Exposes a single high-level tool `browser_vision` that accepts natural language commands and executes multi-step browser workflows with vision feedback.

**Multi-step execution loop:**
1. Parse the natural language command
2. Plan steps (navigate, click, fill, etc.)
3. Execute each step via BrowserEngine
4. After each step, optionally capture screenshot + analyze
5. Decide next action based on visual feedback
6. Return final result with screenshot

This does NOT use a separate LLM call for planning — the main agent loop already does planning. Instead, `browser_vision` provides:
- `browser_analyze`: Analyze current page (screenshot + a11y tree → LLM vision)
- `browser_find_element`: Find element by natural language description
- `browser_smart_click`: Find element by description then click it
- `browser_smart_fill`: Find input by description then fill it

These tools augment the existing browser_action tool by adding vision-based element identification.

## Tool Definitions

New tools exposed (in addition to the 6 existing browser engine tools):

| Tool | Description |
|------|-------------|
| `browser_analyze` | Capture screenshot + a11y tree, send to LLM Vision, return page analysis |
| `browser_find_element` | Find element by natural language description using vision |
| `browser_smart_click` | Find element by description and click it |
| `browser_smart_fill` | Find input field by description and fill it with value |

## Integration Points

### ToolExecutor hook

Add a post-processing step in `ToolExecutor` that calls `ScreenshotProcessor.process_tool_result()` on browser tool results. This converts screenshot tags to proper `Attachment` objects so the LLM can see them in subsequent turns.

This is a minimal change: in `tool_executor.py`, after creating the tool result `LLMMessage`, check if the tool name starts with `browser_` and process attachments.

### LLM Provider

No changes needed — Claude and Gemini already support `LLMMessage.attachments`.

## File Plan

| File | Action | Responsibility |
|------|--------|----------------|
| `src/breadmind/tools/browser_screenshot.py` | Create | Screenshot tag extraction, Attachment conversion |
| `src/breadmind/tools/browser_page_analyzer.py` | Create | Page analysis via LLM Vision (screenshot + a11y) |
| `src/breadmind/tools/browser_vision.py` | Create | High-level vision tools (analyze, find, smart_click/fill) |
| `src/breadmind/core/tool_executor.py` | Modify | Add screenshot post-processing hook for browser tools |
| `src/breadmind/tools/browser_engine.py` | Modify | Register vision tools alongside existing 6 tools |
| `src/breadmind/plugins/builtin/browser/plugin.py` | Modify | Pass LLM provider to BrowserEngine for vision |
| `tests/tools/test_browser_screenshot.py` | Create | Screenshot extraction tests |
| `tests/tools/test_browser_page_analyzer.py` | Create | Page analyzer tests |
| `tests/tools/test_browser_vision.py` | Create | Vision tool tests |

## What This Does NOT Cover

- Macro recording/replay (Sub-project 3)
- Web UI session dashboard and live view (Sub-project 4)
