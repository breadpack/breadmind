# Browser Engine Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular browser engine with session management, advanced actions, network monitoring, and accessibility tree extraction on top of the existing Playwright-based browser tool.

**Architecture:** Existing `browser.py` stays as low-level driver with minimal changes (CDPSession accessor). Five new modules layer on top: SessionManager (lifecycle/pooling), ActionsHandler (hover/drag/upload), NetworkMonitor (CDP Network/Fetch), A11yExtractor (accessibility tree), and BrowserEngine (unified entry point with tool definitions). Playwright handles stability; CDP handles advanced features.

**Tech Stack:** Python 3.12+, Playwright (async API + CDPSession), asyncio, pytest + pytest-asyncio, pydantic (config)

---

### Task 1: Add BrowserConfig to config.py

**Files:**
- Modify: `src/breadmind/config.py:155-171`

- [ ] **Step 1: Add BrowserConfig class**

Add after `NetworkConfig` (before `AppConfig`):

```python
class BrowserConfig(BaseModel):
    """Browser automation engine configuration."""
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    headless: str = "auto"  # "auto" | "true" | "false"
    max_sessions: int = 5
    max_tabs_per_session: int = 10
    idle_timeout_seconds: int = 300
    default_timeout_ms: int = 10000
    viewport_width: int = 1280
    viewport_height: int = 900
    locale: str = "ko-KR"
```

Add to `AppConfig`:

```python
browser: BrowserConfig = Field(default_factory=BrowserConfig)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/config.py
git commit -m "feat(browser): add BrowserConfig to AppConfig"
```

---

### Task 2: Modify browser.py — expose CDPSession and internals

**Files:**
- Modify: `src/breadmind/tools/browser.py`

- [ ] **Step 1: Write test for CDPSession accessor**

Create `tests/tools/test_browser_cdp.py`:

```python
"""Tests for browser.py CDPSession accessor and page/context exposure."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.is_closed.return_value = False
    ctx = AsyncMock()
    ctx.new_cdp_session = AsyncMock(return_value=MagicMock(name="cdp_session"))
    page.context = ctx
    return page


async def test_get_cdp_session(mock_page):
    from breadmind.tools.browser import get_cdp_session

    session = await get_cdp_session(mock_page)
    mock_page.context.new_cdp_session.assert_called_once_with(mock_page)
    assert session is not None


async def test_get_active_page_returns_none_when_no_browser():
    from breadmind.tools.browser import get_active_page

    # Reset global state
    import breadmind.tools.browser as bmod
    bmod._page = None
    result = get_active_page()
    assert result is None


async def test_get_active_context_returns_none_when_no_browser():
    from breadmind.tools.browser import get_active_context

    import breadmind.tools.browser as bmod
    bmod._context = None
    result = get_active_context()
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tools/test_browser_cdp.py -v`
Expected: FAIL (get_cdp_session, get_active_page, get_active_context not found)

- [ ] **Step 3: Add CDPSession accessor and context/page getters to browser.py**

Add after `_close_browser()` function (around line 178):

```python
async def get_cdp_session(page) -> Any:
    """Get CDP session from a Playwright page for direct protocol access."""
    return await page.context.new_cdp_session(page)


def get_active_page() -> Any | None:
    """Return the current active page, or None."""
    return _page


def get_active_context() -> Any | None:
    """Return the current browser context, or None."""
    return _context
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/tools/test_browser_cdp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser.py tests/tools/test_browser_cdp.py
git commit -m "feat(browser): expose CDPSession accessor and page/context getters"
```

---

### Task 3: SessionManager — browser_session.py

**Files:**
- Create: `src/breadmind/tools/browser_session.py`
- Create: `tests/tools/test_browser_session.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_session.py`:

```python
"""Tests for BrowserSession and SessionManager."""
from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# --- BrowserSession dataclass tests ---

def test_browser_session_creation():
    from breadmind.tools.browser_session import BrowserSession

    session = BrowserSession(
        id="s1",
        name="test",
        mode="playwright",
        persistent=False,
        context=MagicMock(),
        page=AsyncMock(),
    )
    assert session.id == "s1"
    assert session.name == "test"
    assert session.persistent is False
    assert session.tabs == {}


def test_browser_session_touch_updates_last_active():
    from breadmind.tools.browser_session import BrowserSession

    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    old = session.last_active
    import time; time.sleep(0.01)
    session.touch()
    assert session.last_active > old


def test_browser_session_is_idle():
    from breadmind.tools.browser_session import BrowserSession

    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    assert not session.is_idle(timeout=300)
    session.last_active = time.time() - 400
    assert session.is_idle(timeout=300)


def test_persistent_session_never_idle():
    from breadmind.tools.browser_session import BrowserSession

    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=True, context=MagicMock(), page=AsyncMock(),
    )
    session.last_active = time.time() - 9999
    assert not session.is_idle(timeout=300)


# --- SessionManager tests ---

async def test_session_manager_create_session():
    from breadmind.tools.browser_session import SessionManager

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    # Mock _launch_context
    mock_ctx = AsyncMock()
    mock_page = AsyncMock()
    mock_page.is_closed.return_value = False
    mock_ctx.new_page = AsyncMock(return_value=mock_page)
    mock_ctx.pages = [mock_page]

    with patch.object(mgr, '_launch_context', return_value=(mock_ctx, mock_page)):
        session = await mgr.create(name="test-session", mode="playwright", persistent=False)

    assert session.name == "test-session"
    assert session.id in mgr._sessions
    assert len(mgr._sessions) == 1


async def test_session_manager_get_session():
    from breadmind.tools.browser_session import SessionManager, BrowserSession

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    s = BrowserSession(
        id="s1", name="my-session", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    mgr._sessions["s1"] = s

    assert mgr.get("s1") is s
    assert mgr.get_by_name("my-session") is s
    assert mgr.get("nonexistent") is None


async def test_session_manager_close_session():
    from breadmind.tools.browser_session import SessionManager, BrowserSession

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    s = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=mock_ctx, page=AsyncMock(),
    )
    mgr._sessions["s1"] = s

    await mgr.close("s1")
    assert "s1" not in mgr._sessions
    mock_ctx.close.assert_called_once()


async def test_session_manager_max_sessions_enforced():
    from breadmind.tools.browser_session import SessionManager

    mgr = SessionManager(max_sessions=2, max_tabs=10, idle_timeout=300)

    mock_ctx = AsyncMock()
    mock_page = AsyncMock()
    mock_page.is_closed.return_value = False
    mock_ctx.pages = [mock_page]

    with patch.object(mgr, '_launch_context', return_value=(mock_ctx, mock_page)):
        await mgr.create(name="s1", mode="playwright", persistent=False)
        await mgr.create(name="s2", mode="playwright", persistent=False)
        with pytest.raises(RuntimeError, match="Maximum sessions"):
            await mgr.create(name="s3", mode="playwright", persistent=False)


async def test_session_manager_list_sessions():
    from breadmind.tools.browser_session import SessionManager, BrowserSession

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mgr._sessions["s1"] = BrowserSession(
        id="s1", name="a", mode="playwright",
        persistent=True, context=MagicMock(), page=AsyncMock(),
    )
    mgr._sessions["s2"] = BrowserSession(
        id="s2", name="b", mode="cdp",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    listing = mgr.list_sessions()
    assert len(listing) == 2
    assert listing[0]["id"] == "s1"


async def test_cleanup_idle_transient_sessions():
    from breadmind.tools.browser_session import SessionManager, BrowserSession

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    s = BrowserSession(
        id="s1", name="temp", mode="playwright",
        persistent=False, context=mock_ctx, page=AsyncMock(),
    )
    s.last_active = time.time() - 400  # idle
    mgr._sessions["s1"] = s

    removed = await mgr.cleanup_idle()
    assert "s1" in removed
    assert "s1" not in mgr._sessions


async def test_cleanup_skips_persistent_sessions():
    from breadmind.tools.browser_session import SessionManager, BrowserSession

    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    s = BrowserSession(
        id="s1", name="perm", mode="playwright",
        persistent=True, context=MagicMock(), page=AsyncMock(),
    )
    s.last_active = time.time() - 9999
    mgr._sessions["s1"] = s

    removed = await mgr.cleanup_idle()
    assert len(removed) == 0
    assert "s1" in mgr._sessions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_browser_session.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement browser_session.py**

Create `src/breadmind/tools/browser_session.py`:

```python
"""Browser session management — multi-instance pool with lifecycle control."""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """A managed browser session wrapping a Playwright BrowserContext."""

    id: str
    name: str
    mode: str  # "playwright" | "cdp" | "user_chrome"
    persistent: bool
    context: Any  # Playwright BrowserContext
    page: Any  # Active Playwright Page

    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    tabs: dict[str, Any] = field(default_factory=dict)  # tab_id -> Page

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = time.time()

    def is_idle(self, timeout: int) -> bool:
        """Check if this session has been idle longer than timeout seconds."""
        if self.persistent:
            return False
        return (time.time() - self.last_active) > timeout

    def to_dict(self) -> dict:
        """Serialize session metadata (no Playwright objects)."""
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "persistent": self.persistent,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "tab_count": len(self.context.pages) if self.context else 0,
        }


def _detect_headless() -> bool:
    """Auto-detect whether to run headless based on display availability."""
    import platform
    system = platform.system()
    if system == "Linux":
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    # Windows and macOS always have a display if running desktop
    # For Docker/CI, DISPLAY won't be set even on these platforms
    if system == "Windows":
        try:
            import ctypes
            return ctypes.windll.user32.GetDesktopWindow() == 0
        except Exception:
            return True
    return False  # macOS: assume headed


def resolve_headless(config_value: str) -> bool:
    """Resolve headless setting from config string."""
    if config_value == "true":
        return True
    if config_value == "false":
        return False
    return _detect_headless()


class SessionManager:
    """Manages multiple browser sessions with lifecycle control."""

    def __init__(
        self,
        max_sessions: int = 5,
        max_tabs: int = 10,
        idle_timeout: int = 300,
        headless: str = "auto",
        viewport_width: int = 1280,
        viewport_height: int = 900,
        locale: str = "ko-KR",
    ) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._max_sessions = max_sessions
        self._max_tabs = max_tabs
        self._idle_timeout = idle_timeout
        self._headless = headless
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._locale = locale
        self._playwright: Any = None
        self._browser: Any = None

    async def _ensure_playwright(self) -> Any:
        """Ensure Playwright instance is running."""
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise RuntimeError(
                    "playwright is not installed. Run: pip install 'breadmind[browser]' "
                    "then: playwright install chromium"
                )
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_browser(self) -> Any:
        """Ensure shared Browser instance is running."""
        if self._browser is None or not self._browser.is_connected():
            pw = await self._ensure_playwright()
            headless = resolve_headless(self._headless)
            self._browser = await pw.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        return self._browser

    async def _launch_context(self, mode: str, cdp_url: str = "") -> tuple[Any, Any]:
        """Launch a new BrowserContext and return (context, page)."""
        if mode == "cdp":
            pw = await self._ensure_playwright()
            browser = await pw.chromium.connect_over_cdp(
                cdp_url or "http://localhost:9222"
            )
            contexts = browser.contexts
            ctx = contexts[0] if contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            return ctx, page

        browser = await self._ensure_browser()
        ctx = await browser.new_context(
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            locale=self._locale,
        )
        page = await ctx.new_page()
        return ctx, page

    async def create(
        self,
        name: str = "",
        mode: str = "playwright",
        persistent: bool = False,
        cdp_url: str = "",
    ) -> BrowserSession:
        """Create a new browser session."""
        if len(self._sessions) >= self._max_sessions:
            raise RuntimeError(
                f"Maximum sessions ({self._max_sessions}) reached. "
                f"Close an existing session first."
            )

        session_id = uuid.uuid4().hex[:8]
        if not name:
            name = f"session-{session_id}"

        ctx, page = await self._launch_context(mode, cdp_url)

        session = BrowserSession(
            id=session_id,
            name=name,
            mode=mode,
            persistent=persistent,
            context=ctx,
            page=page,
        )
        self._sessions[session_id] = session
        logger.info("Created browser session %s (%s, persistent=%s)", name, mode, persistent)
        return session

    def get(self, session_id: str) -> BrowserSession | None:
        """Get session by ID."""
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def get_by_name(self, name: str) -> BrowserSession | None:
        """Get session by name."""
        for session in self._sessions.values():
            if session.name == name:
                session.touch()
                return session
        return None

    def get_most_recent(self) -> BrowserSession | None:
        """Get the most recently active session."""
        if not self._sessions:
            return None
        session = max(self._sessions.values(), key=lambda s: s.last_active)
        session.touch()
        return session

    def list_sessions(self) -> list[dict]:
        """List all sessions as dicts."""
        return [s.to_dict() for s in self._sessions.values()]

    async def close(self, session_id: str) -> None:
        """Close and remove a session."""
        session = self._sessions.pop(session_id, None)
        if session and session.context:
            try:
                await session.context.close()
            except Exception as e:
                logger.warning("Error closing session %s: %s", session_id, e)

    async def close_all(self) -> None:
        """Close all sessions and cleanup."""
        for sid in list(self._sessions):
            await self.close(sid)
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def cleanup_idle(self) -> list[str]:
        """Close transient sessions that have been idle too long."""
        removed = []
        for sid, session in list(self._sessions.items()):
            if session.is_idle(self._idle_timeout):
                await self.close(sid)
                removed.append(sid)
                logger.info("Cleaned up idle session %s (%s)", session.name, sid)
        return removed

    async def new_tab(self, session_id: str, url: str = "") -> Any:
        """Open a new tab in a session."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if len(session.context.pages) >= self._max_tabs:
            raise RuntimeError(
                f"Maximum tabs ({self._max_tabs}) reached for session {session.name}."
            )
        page = await session.context.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        session.page = page
        session.touch()
        return page
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_browser_session.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_session.py tests/tools/test_browser_session.py
git commit -m "feat(browser): add SessionManager with multi-instance pool and lifecycle"
```

---

### Task 4: ActionsHandler — browser_actions.py

**Files:**
- Create: `src/breadmind/tools/browser_actions.py`
- Create: `tests/tools/test_browser_actions.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_actions.py`:

```python
"""Tests for advanced browser actions."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example")
    page.evaluate = AsyncMock(return_value={"key": "value"})
    # Mock locator chain
    locator = AsyncMock()
    locator.first = locator
    page.locator = MagicMock(return_value=locator)
    page.query_selector = AsyncMock(return_value=AsyncMock())
    return page


async def test_hover(mock_page):
    from breadmind.tools.browser_actions import hover
    result = await hover(mock_page, selector="#btn")
    mock_page.hover.assert_called_once_with("#btn", timeout=10000)
    assert "Hovered" in result


async def test_drag_drop(mock_page):
    from breadmind.tools.browser_actions import drag_drop
    result = await drag_drop(mock_page, source="#a", target="#b")
    mock_page.drag_and_drop.assert_called_once_with("#a", "#b", timeout=10000)
    assert "Dragged" in result


async def test_upload_file(mock_page):
    from breadmind.tools.browser_actions import upload_file
    mock_input = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=mock_input)
    result = await upload_file(mock_page, selector="input[type=file]", file_paths=["/tmp/test.txt"])
    mock_input.set_input_files.assert_called_once_with(["/tmp/test.txt"])
    assert "Uploaded" in result


async def test_upload_file_element_not_found(mock_page):
    from breadmind.tools.browser_actions import upload_file
    mock_page.query_selector = AsyncMock(return_value=None)
    result = await upload_file(mock_page, selector="input[type=file]", file_paths=["/tmp/x.txt"])
    assert "[error]" in result


async def test_select_option(mock_page):
    from breadmind.tools.browser_actions import select_option
    mock_page.select_option = AsyncMock(return_value=["opt1"])
    result = await select_option(mock_page, selector="select#lang", value="ko")
    mock_page.select_option.assert_called_once()
    assert "Selected" in result


async def test_scroll_down(mock_page):
    from breadmind.tools.browser_actions import scroll
    result = await scroll(mock_page, direction="down", amount=500)
    mock_page.evaluate.assert_called_once()
    assert "Scrolled" in result


async def test_press_key(mock_page):
    from breadmind.tools.browser_actions import press_key
    result = await press_key(mock_page, key="Enter")
    mock_page.keyboard.press.assert_called_once_with("Enter")
    assert "Pressed" in result


async def test_get_cookies(mock_page):
    from breadmind.tools.browser_actions import get_cookies
    mock_page.context.cookies = AsyncMock(return_value=[{"name": "sid", "value": "abc"}])
    result = await get_cookies(mock_page)
    assert isinstance(result, list)
    assert result[0]["name"] == "sid"


async def test_export_pdf(mock_page):
    from breadmind.tools.browser_actions import export_pdf
    mock_page.pdf = AsyncMock(return_value=b"%PDF-fake")
    result = await export_pdf(mock_page)
    assert "PDF" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_browser_actions.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement browser_actions.py**

Create `src/breadmind/tools/browser_actions.py`:

```python
"""Advanced browser actions — extends base browser.py capabilities."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def hover(page: Any, selector: str, timeout: int = 10000) -> str:
    """Hover over an element."""
    await page.hover(selector, timeout=timeout)
    return f"Hovered over: {selector}"


async def drag_drop(
    page: Any, source: str, target: str, timeout: int = 10000,
) -> str:
    """Drag element from source selector to target selector."""
    await page.drag_and_drop(source, target, timeout=timeout)
    return f"Dragged {source} to {target}"


async def upload_file(
    page: Any, selector: str, file_paths: list[str],
) -> str:
    """Upload files to a file input element."""
    element = await page.query_selector(selector)
    if not element:
        return f"[error] Element not found: {selector}"
    await element.set_input_files(file_paths)
    names = [p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in file_paths]
    return f"Uploaded {len(file_paths)} file(s): {', '.join(names)}"


async def select_option(
    page: Any,
    selector: str,
    value: str = "",
    label: str = "",
    index: int | None = None,
) -> str:
    """Select an option from a dropdown."""
    kwargs: dict[str, Any] = {}
    if value:
        kwargs["value"] = value
    elif label:
        kwargs["label"] = label
    elif index is not None:
        kwargs["index"] = index
    else:
        return "[error] Provide value, label, or index for select_option"
    selected = await page.select_option(selector, **kwargs)
    return f"Selected: {selected}"


async def scroll(
    page: Any,
    direction: str = "down",
    amount: int = 500,
    selector: str = "",
) -> str:
    """Scroll page or element."""
    dy = amount if direction == "down" else -amount
    if selector:
        js = f"document.querySelector('{selector}').scrollBy(0, {dy})"
    else:
        js = f"window.scrollBy(0, {dy})"
    await page.evaluate(js)
    return f"Scrolled {direction} by {amount}px"


async def press_key(page: Any, key: str, modifiers: str = "") -> str:
    """Press a keyboard key, optionally with modifiers."""
    combo = f"{modifiers}+{key}" if modifiers else key
    await page.keyboard.press(combo)
    return f"Pressed: {combo}"


async def get_cookies(page: Any, urls: list[str] | None = None) -> list[dict]:
    """Get cookies from the browser context."""
    if urls:
        return await page.context.cookies(urls)
    return await page.context.cookies()


async def set_cookie(page: Any, cookie: dict) -> str:
    """Set a cookie in the browser context."""
    await page.context.add_cookies([cookie])
    return f"Cookie set: {cookie.get('name', '?')}"


async def get_storage(page: Any, storage_type: str = "local") -> dict:
    """Read localStorage or sessionStorage."""
    js = f"JSON.stringify(Object.fromEntries(Object.entries({storage_type}Storage)))"
    raw = await page.evaluate(js)
    return json.loads(raw) if raw else {}


async def wait_for_navigation(
    page: Any, url_pattern: str = "", timeout: int = 10000,
) -> str:
    """Wait for navigation to complete."""
    if url_pattern:
        await page.wait_for_url(url_pattern, timeout=timeout)
    else:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    title = await page.title()
    return f"Navigation complete: {page.url}\nTitle: {title}"


async def export_pdf(page: Any, path: str = "") -> str:
    """Export page as PDF. Returns base64 if no path given."""
    pdf_bytes = await page.pdf()
    if path:
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        return f"PDF saved to {path} ({len(pdf_bytes)} bytes)"
    encoded = base64.b64encode(pdf_bytes).decode()
    return f"PDF exported ({len(pdf_bytes)} bytes)\n[pdf_base64]{encoded}[/pdf_base64]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_browser_actions.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_actions.py tests/tools/test_browser_actions.py
git commit -m "feat(browser): add advanced actions (hover, drag, upload, scroll, keys, cookies)"
```

---

### Task 5: NetworkMonitor — browser_network.py

**Files:**
- Create: `src/breadmind/tools/browser_network.py`
- Create: `tests/tools/test_browser_network.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_network.py`:

```python
"""Tests for browser network monitoring via CDP."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call


@pytest.fixture
def mock_cdp():
    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={})
    return cdp


async def test_request_entry_creation():
    from breadmind.tools.browser_network import RequestEntry
    entry = RequestEntry(
        url="https://api.example.com/data",
        method="GET",
        status=200,
        request_headers={"Accept": "application/json"},
        response_headers={"Content-Type": "application/json"},
        body_size=1024,
        duration_ms=150.0,
        resource_type="xhr",
        timestamp=1000.0,
    )
    assert entry.url == "https://api.example.com/data"
    assert entry.status == 200


async def test_network_monitor_start_capture(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    await monitor.start_capture()
    assert monitor._capturing is True
    mock_cdp.send.assert_any_call("Network.enable", {})


async def test_network_monitor_stop_capture(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    entries = await monitor.stop_capture()
    assert monitor._capturing is False
    assert isinstance(entries, list)


async def test_network_monitor_on_request(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    monitor._on_request_will_be_sent({
        "requestId": "r1",
        "request": {
            "url": "https://example.com/api",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        },
        "type": "XHR",
        "timestamp": 1000.0,
    })
    assert "r1" in monitor._pending


async def test_network_monitor_on_response(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    monitor._pending["r1"] = {
        "url": "https://example.com/api",
        "method": "POST",
        "request_headers": {},
        "resource_type": "xhr",
        "timestamp": 1000.0,
    }
    monitor._on_response_received({
        "requestId": "r1",
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "encodedDataLength": 512,
        },
        "timestamp": 1000.15,
    })
    assert len(monitor._entries) == 1
    assert monitor._entries[0].status == 200
    assert monitor._entries[0].duration_ms == pytest.approx(150.0, abs=1.0)


async def test_network_monitor_max_entries(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp, max_entries=3)
    monitor._capturing = True
    for i in range(5):
        monitor._pending[f"r{i}"] = {
            "url": f"https://example.com/{i}",
            "method": "GET",
            "request_headers": {},
            "resource_type": "document",
            "timestamp": 1000.0 + i,
        }
        monitor._on_response_received({
            "requestId": f"r{i}",
            "response": {"status": 200, "headers": {}, "encodedDataLength": 100},
            "timestamp": 1000.1 + i,
        })
    assert len(monitor._entries) == 3
    # Oldest evicted — entries should be the last 3
    assert monitor._entries[0].url == "https://example.com/2"


async def test_block_urls(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    await monitor.block_urls(["*analytics*", "*ads*"])
    mock_cdp.send.assert_any_call("Network.setBlockedURLs", {"urls": ["*analytics*", "*ads*"]})


async def test_export_har(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor, RequestEntry
    monitor = NetworkMonitor(mock_cdp)
    monitor._entries = [
        RequestEntry(
            url="https://example.com",
            method="GET",
            status=200,
            request_headers={},
            response_headers={},
            body_size=1024,
            duration_ms=100.0,
            resource_type="document",
            timestamp=1000.0,
        )
    ]
    har = monitor.export_har()
    assert "log" in har
    assert len(har["log"]["entries"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_browser_network.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement browser_network.py**

Create `src/breadmind/tools/browser_network.py`:

```python
"""Browser network monitoring via CDP Network/Fetch domains."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RequestEntry:
    """Captured network request/response pair."""

    url: str
    method: str
    status: int
    request_headers: dict
    response_headers: dict
    body_size: int
    duration_ms: float
    resource_type: str
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "body_size": self.body_size,
            "duration_ms": round(self.duration_ms, 1),
            "resource_type": self.resource_type,
        }


class NetworkMonitor:
    """Captures and analyzes network traffic via CDP session."""

    def __init__(self, cdp_session: Any, max_entries: int = 1000) -> None:
        self._cdp = cdp_session
        self._max_entries = max_entries
        self._capturing = False
        self._entries: list[RequestEntry] = []
        self._pending: dict[str, dict] = {}
        self._url_filters: list[str] = []

    async def start_capture(self, url_filters: list[str] | None = None) -> None:
        """Begin capturing network traffic."""
        self._entries.clear()
        self._pending.clear()
        self._url_filters = url_filters or []
        self._capturing = True
        await self._cdp.send("Network.enable", {})
        self._cdp.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._cdp.on("Network.responseReceived", self._on_response_received)
        logger.info("Network capture started (filters=%s)", self._url_filters)

    async def stop_capture(self) -> list[RequestEntry]:
        """Stop capturing and return collected entries."""
        self._capturing = False
        try:
            await self._cdp.send("Network.disable", {})
        except Exception:
            pass
        entries = list(self._entries)
        logger.info("Network capture stopped (%d entries)", len(entries))
        return entries

    def _on_request_will_be_sent(self, params: dict) -> None:
        """CDP event handler for outgoing requests."""
        if not self._capturing:
            return
        req = params.get("request", {})
        url = req.get("url", "")

        # Apply URL filters if set
        if self._url_filters:
            if not any(f in url for f in self._url_filters):
                return

        self._pending[params["requestId"]] = {
            "url": url,
            "method": req.get("method", "GET"),
            "request_headers": req.get("headers", {}),
            "resource_type": params.get("type", "other").lower(),
            "timestamp": params.get("timestamp", 0),
        }

    def _on_response_received(self, params: dict) -> None:
        """CDP event handler for received responses."""
        if not self._capturing:
            return
        request_id = params.get("requestId")
        pending = self._pending.pop(request_id, None)
        if not pending:
            return

        resp = params.get("response", {})
        duration_ms = (params.get("timestamp", 0) - pending["timestamp"]) * 1000

        entry = RequestEntry(
            url=pending["url"],
            method=pending["method"],
            status=resp.get("status", 0),
            request_headers=pending["request_headers"],
            response_headers=resp.get("headers", {}),
            body_size=resp.get("encodedDataLength", 0),
            duration_ms=duration_ms,
            resource_type=pending["resource_type"],
            timestamp=pending["timestamp"],
        )
        self._entries.append(entry)

        # Evict oldest if over limit
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

    async def block_urls(self, patterns: list[str]) -> None:
        """Block network requests matching URL patterns."""
        await self._cdp.send("Network.setBlockedURLs", {"urls": patterns})
        logger.info("Blocking URLs: %s", patterns)

    async def unblock_urls(self) -> None:
        """Remove all URL blocks."""
        await self._cdp.send("Network.setBlockedURLs", {"urls": []})

    def export_har(self) -> dict:
        """Export captured traffic as HAR-like JSON structure."""
        return {
            "log": {
                "version": "1.2",
                "entries": [
                    {
                        "request": {
                            "method": e.method,
                            "url": e.url,
                            "headers": [
                                {"name": k, "value": v}
                                for k, v in e.request_headers.items()
                            ],
                        },
                        "response": {
                            "status": e.status,
                            "headers": [
                                {"name": k, "value": v}
                                for k, v in e.response_headers.items()
                            ],
                            "content": {"size": e.body_size},
                        },
                        "time": round(e.duration_ms, 1),
                    }
                    for e in self._entries
                ],
            }
        }

    def get_summary(self) -> dict:
        """Get a summary of captured traffic."""
        if not self._entries:
            return {"total": 0}
        by_type: dict[str, int] = {}
        total_size = 0
        for e in self._entries:
            by_type[e.resource_type] = by_type.get(e.resource_type, 0) + 1
            total_size += e.body_size
        return {
            "total": len(self._entries),
            "by_type": by_type,
            "total_size_bytes": total_size,
            "avg_duration_ms": round(
                sum(e.duration_ms for e in self._entries) / len(self._entries), 1
            ),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_browser_network.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_network.py tests/tools/test_browser_network.py
git commit -m "feat(browser): add CDP-based network monitor with capture, blocking, HAR export"
```

---

### Task 6: A11yExtractor — browser_a11y.py

**Files:**
- Create: `src/breadmind/tools/browser_a11y.py`
- Create: `tests/tools/test_browser_a11y.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_a11y.py`:

```python
"""Tests for accessibility tree extraction."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


def _make_ax_node(role: str, name: str = "", value: str = "",
                  children: list | None = None, **props) -> dict:
    """Helper to build CDP AXNode-like dicts."""
    node = {
        "role": {"value": role},
        "name": {"value": name},
        "properties": [{"name": k, "value": {"value": v}} for k, v in props.items()],
        "children": children or [],
    }
    if value:
        node["value"] = {"value": value}
    return node


async def test_extract_simple_tree():
    from breadmind.tools.browser_a11y import A11yExtractor

    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={
        "nodes": [
            _make_ax_node("RootWebArea", "Example Page", children=[
                _make_ax_node("heading", "Dashboard", level="1"),
                _make_ax_node("button", "Sign In"),
                _make_ax_node("textbox", "Email", value=""),
            ]),
        ],
    })

    extractor = A11yExtractor(cdp)
    tree = await extractor.extract()
    assert len(tree) > 0


async def test_format_compact():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode

    nodes = [
        AXNode(role="heading", name="Dashboard", properties={"level": "1"}),
        AXNode(role="button", name="Sign In"),
        AXNode(role="textbox", name="Email", value="user@test.com"),
    ]
    text = A11yExtractor.format_compact(nodes)
    assert '[heading level=1 "Dashboard"]' in text
    assert '[button "Sign In"]' in text
    assert '[textbox "Email" value="user@test.com"]' in text


async def test_format_compact_with_depth():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode

    parent = AXNode(
        role="navigation", name="Main Nav",
        children=[
            AXNode(role="link", name="Home"),
            AXNode(role="link", name="Settings"),
        ],
    )
    text = A11yExtractor.format_compact([parent])
    assert "[navigation" in text
    assert '  [link "Home"]' in text


async def test_filter_interactive_only():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode

    nodes = [
        AXNode(role="heading", name="Title"),
        AXNode(role="button", name="Submit"),
        AXNode(role="textbox", name="Name"),
        AXNode(role="paragraph", name="Some text"),
        AXNode(role="link", name="Click here"),
    ]
    filtered = A11yExtractor.filter_interactive(nodes)
    roles = [n.role for n in filtered]
    assert "button" in roles
    assert "textbox" in roles
    assert "link" in roles
    assert "heading" not in roles
    assert "paragraph" not in roles


async def test_max_depth_respected():
    from breadmind.tools.browser_a11y import A11yExtractor

    cdp = AsyncMock()
    # Build deep tree: root -> div -> div -> div -> button
    deep = _make_ax_node("button", "Deep Button")
    for i in range(5):
        deep = _make_ax_node("generic", f"layer-{i}", children=[deep])
    root = _make_ax_node("RootWebArea", "Page", children=[deep])

    cdp.send = AsyncMock(return_value={"nodes": [root]})
    extractor = A11yExtractor(cdp, max_depth=3)
    tree = await extractor.extract()
    text = A11yExtractor.format_compact(tree)
    # Button at depth 6 should not appear when max_depth=3
    assert "Deep Button" not in text


async def test_token_estimate():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode

    nodes = [
        AXNode(role="button", name="OK"),
        AXNode(role="textbox", name="Email", value="test@test.com"),
    ]
    text = A11yExtractor.format_compact(nodes)
    estimate = A11yExtractor.estimate_tokens(text)
    assert estimate > 0
    assert isinstance(estimate, int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_browser_a11y.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement browser_a11y.py**

Create `src/breadmind/tools/browser_a11y.py`:

```python
"""Accessibility tree extraction via CDP for LLM-friendly page understanding."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

INTERACTIVE_ROLES = frozenset({
    "button", "textbox", "checkbox", "radio", "combobox", "listbox",
    "menuitem", "link", "searchbox", "slider", "spinbutton", "switch",
    "tab", "menubar", "menu", "option", "treeitem",
})


@dataclass
class AXNode:
    """Simplified accessibility tree node."""

    role: str
    name: str = ""
    value: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    children: list[AXNode] = field(default_factory=list)


class A11yExtractor:
    """Extract and format accessibility trees via CDP."""

    def __init__(self, cdp_session: Any, max_depth: int = 10) -> None:
        self._cdp = cdp_session
        self._max_depth = max_depth

    async def extract(self) -> list[AXNode]:
        """Extract the full accessibility tree from CDP."""
        result = await self._cdp.send("Accessibility.getFullAXTree", {})
        raw_nodes = result.get("nodes", [])
        if not raw_nodes:
            return []
        root = raw_nodes[0]
        return self._parse_children(root.get("children", []), depth=0)

    def _parse_children(self, children: list[dict], depth: int) -> list[AXNode]:
        """Recursively parse CDP AX nodes into AXNode dataclasses."""
        if depth >= self._max_depth:
            return []
        nodes = []
        for raw in children:
            role = raw.get("role", {}).get("value", "unknown")
            if role in ("none", "generic", "InlineTextBox"):
                # Pass through to children without creating a node
                nodes.extend(
                    self._parse_children(raw.get("children", []), depth)
                )
                continue

            name = raw.get("name", {}).get("value", "")
            value = raw.get("value", {}).get("value", "") if "value" in raw else ""
            props: dict[str, str] = {}
            for prop in raw.get("properties", []):
                prop_name = prop.get("name", "")
                prop_val = prop.get("value", {}).get("value", "")
                if prop_val:
                    props[prop_name] = str(prop_val)

            child_nodes = self._parse_children(
                raw.get("children", []), depth + 1
            )
            nodes.append(AXNode(
                role=role,
                name=name,
                value=str(value) if value else "",
                properties=props,
                children=child_nodes,
            ))
        return nodes

    @staticmethod
    def format_compact(nodes: list[AXNode], indent: int = 0) -> str:
        """Format AXNodes into compact LLM-friendly text."""
        lines: list[str] = []
        prefix = "  " * indent
        for node in nodes:
            parts = [f"[{node.role}"]
            for k, v in node.properties.items():
                parts.append(f"{k}={v}")
            if node.name:
                parts.append(f'"{node.name}"')
            if node.value:
                parts.append(f'value="{node.value}"')
            line = prefix + " ".join(parts) + "]"
            lines.append(line)
            if node.children:
                lines.append(
                    A11yExtractor.format_compact(node.children, indent + 1)
                )
        return "\n".join(lines)

    @staticmethod
    def filter_interactive(nodes: list[AXNode]) -> list[AXNode]:
        """Filter to only interactive elements (buttons, inputs, links, etc.)."""
        result: list[AXNode] = []
        for node in nodes:
            if node.role in INTERACTIVE_ROLES:
                result.append(node)
            # Recurse into children regardless
            result.extend(A11yExtractor.filter_interactive(node.children))
        return result

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token count estimate (1 token ~ 4 chars for English/code)."""
        return max(1, len(text) // 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_browser_a11y.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_a11y.py tests/tools/test_browser_a11y.py
git commit -m "feat(browser): add accessibility tree extractor with compact LLM-friendly format"
```

---

### Task 7: BrowserEngine — browser_engine.py (unified entry point)

**Files:**
- Create: `src/breadmind/tools/browser_engine.py`
- Create: `tests/tools/test_browser_engine.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_engine.py`:

```python
"""Tests for BrowserEngine unified entry point."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def engine():
    from breadmind.tools.browser_engine import BrowserEngine

    e = BrowserEngine.__new__(BrowserEngine)
    e._session_mgr = MagicMock()
    e._network_monitors = {}
    e._a11y_extractors = {}
    return e


async def test_session_create(engine):
    from breadmind.tools.browser_engine import BrowserEngine

    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_session.name = "test"
    mock_session.to_dict.return_value = {"id": "s1", "name": "test"}
    engine._session_mgr.create = AsyncMock(return_value=mock_session)

    result = await engine.handle_session(action="create", name="test", mode="playwright")
    assert "s1" in result


async def test_session_list(engine):
    engine._session_mgr.list_sessions.return_value = [
        {"id": "s1", "name": "a", "mode": "playwright", "persistent": True, "tab_count": 2},
    ]
    result = await engine.handle_session(action="list")
    assert "s1" in result
    assert "a" in result


async def test_session_close(engine):
    engine._session_mgr.close = AsyncMock()
    result = await engine.handle_session(action="close", session="s1")
    engine._session_mgr.close.assert_called_once_with("s1")
    assert "Closed" in result


async def test_resolve_session_by_name(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    engine._session_mgr.get.return_value = None
    engine._session_mgr.get_by_name.return_value = mock_session

    result = engine._resolve_session("my-session")
    assert result is mock_session


async def test_resolve_session_auto_creates(engine):
    engine._session_mgr.get.return_value = None
    engine._session_mgr.get_by_name.return_value = None
    engine._session_mgr.get_most_recent.return_value = None

    mock_session = MagicMock()
    mock_session.id = "auto"
    engine._session_mgr.create = AsyncMock(return_value=mock_session)

    result = await engine._resolve_session_or_create("")
    assert result is mock_session


async def test_navigate(engine):
    mock_session = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://example.com"
    mock_page.title = AsyncMock(return_value="Example")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_session.page = mock_page
    mock_session.touch = MagicMock()

    engine._resolve_session_or_create = AsyncMock(return_value=mock_session)

    result = await engine.navigate(session="s1", url="https://example.com")
    assert "example.com" in result.lower()


async def test_get_a11y_tree(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_page = AsyncMock()
    mock_session.page = mock_page
    mock_session.touch = MagicMock()

    engine._resolve_session_or_create = AsyncMock(return_value=mock_session)

    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock(return_value={
        "nodes": [{
            "role": {"value": "RootWebArea"},
            "name": {"value": "Page"},
            "properties": [],
            "children": [
                {
                    "role": {"value": "button"},
                    "name": {"value": "OK"},
                    "properties": [],
                    "children": [],
                },
            ],
        }],
    })

    with patch("breadmind.tools.browser_engine.get_cdp_session", return_value=mock_cdp):
        result = await engine.get_a11y_tree(session="s1")
    assert "button" in result
    assert "OK" in result


async def test_get_tool_definitions():
    from breadmind.tools.browser_engine import BrowserEngine

    e = BrowserEngine.__new__(BrowserEngine)
    tools = e.get_tool_functions()
    names = [f.__name__ for f in tools]
    assert "browser_session" in names
    assert "browser_navigate" in names
    assert "browser_action" in names
    assert "browser_screenshot" in names
    assert "browser_a11y_tree" in names
    assert "browser_network" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_browser_engine.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement browser_engine.py**

Create `src/breadmind/tools/browser_engine.py`:

```python
"""Unified browser engine — entry point for all browser operations."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Callable

from breadmind.tools.browser import get_cdp_session
from breadmind.tools.browser_session import SessionManager, BrowserSession
from breadmind.tools.browser_actions import (
    hover, drag_drop, upload_file, select_option, scroll,
    press_key, get_cookies, set_cookie, get_storage,
    wait_for_navigation, export_pdf,
)
from breadmind.tools.browser_a11y import A11yExtractor
from breadmind.tools.browser_network import NetworkMonitor
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class BrowserEngine:
    """Orchestrates session management, actions, network, and a11y."""

    def __init__(
        self,
        max_sessions: int = 5,
        max_tabs: int = 10,
        idle_timeout: int = 300,
        headless: str = "auto",
        viewport_width: int = 1280,
        viewport_height: int = 900,
        locale: str = "ko-KR",
        default_timeout_ms: int = 10000,
    ) -> None:
        self._session_mgr = SessionManager(
            max_sessions=max_sessions,
            max_tabs=max_tabs,
            idle_timeout=idle_timeout,
            headless=headless,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            locale=locale,
        )
        self._default_timeout = default_timeout_ms
        self._network_monitors: dict[str, NetworkMonitor] = {}
        self._a11y_extractors: dict[str, A11yExtractor] = {}

    def _resolve_session(self, session: str) -> BrowserSession | None:
        """Resolve a session by ID or name."""
        s = self._session_mgr.get(session)
        if s:
            return s
        return self._session_mgr.get_by_name(session)

    async def _resolve_session_or_create(self, session: str) -> BrowserSession:
        """Resolve session, or use most recent, or auto-create transient."""
        if session:
            s = self._resolve_session(session)
            if s:
                return s
        s = self._session_mgr.get_most_recent()
        if s:
            return s
        return await self._session_mgr.create(persistent=False)

    # --- Session management ---

    async def handle_session(
        self, action: str, name: str = "", session: str = "",
        mode: str = "playwright", persistent: bool = False,
        cdp_url: str = "",
    ) -> str:
        """Handle session lifecycle actions."""
        if action == "create":
            s = await self._session_mgr.create(
                name=name, mode=mode, persistent=persistent, cdp_url=cdp_url,
            )
            return f"Session created: {s.name} (id={s.id}, persistent={persistent})"

        if action == "list":
            sessions = self._session_mgr.list_sessions()
            if not sessions:
                return "No active browser sessions."
            lines = []
            for s in sessions:
                flag = " [persistent]" if s.get("persistent") else ""
                lines.append(
                    f"  {s['id']} | {s['name']} | {s['mode']} | "
                    f"tabs={s.get('tab_count', 0)}{flag}"
                )
            return f"Active sessions ({len(sessions)}):\n" + "\n".join(lines)

        if action == "close":
            target = session or name
            if not target:
                return "[error] Provide session ID or name to close."
            s = self._resolve_session(target)
            if not s:
                return f"[error] Session not found: {target}"
            self._network_monitors.pop(s.id, None)
            self._a11y_extractors.pop(s.id, None)
            await self._session_mgr.close(s.id)
            return f"Closed session: {s.name} ({s.id})"

        if action == "close_all":
            self._network_monitors.clear()
            self._a11y_extractors.clear()
            await self._session_mgr.close_all()
            return "All sessions closed."

        return f"[error] Unknown session action: {action}. Use: create, list, close, close_all"

    # --- Navigation ---

    async def navigate(self, session: str = "", url: str = "", wait_until: str = "domcontentloaded") -> str:
        """Navigate to URL in a session."""
        if not url:
            return "[error] url is required"
        s = await self._resolve_session_or_create(session)
        resp = await s.page.goto(url, timeout=self._default_timeout, wait_until=wait_until)
        title = await s.page.title()
        s.touch()
        status = resp.status if resp else "unknown"
        return f"Navigated to: {s.page.url}\nTitle: {title}\nStatus: {status}\nSession: {s.name}"

    # --- Actions ---

    async def do_action(self, session: str = "", action: str = "", **kwargs) -> str:
        """Execute an advanced browser action."""
        s = await self._resolve_session_or_create(session)
        page = s.page
        timeout = kwargs.pop("timeout", self._default_timeout)

        try:
            if action == "click":
                selector = kwargs.get("selector", "")
                text = kwargs.get("text", "")
                if selector:
                    await page.click(selector, timeout=timeout)
                elif text:
                    await page.get_by_text(text, exact=False).first.click(timeout=timeout)
                else:
                    return "[error] selector or text required for click"
                s.touch()
                return f"Clicked: {selector or text}\nURL: {page.url}"

            if action == "fill":
                await page.fill(kwargs["selector"], kwargs.get("value", ""), timeout=timeout)
                s.touch()
                return f"Filled: {kwargs['selector']}"

            if action == "hover":
                result = await hover(page, kwargs["selector"], timeout)
                s.touch()
                return result

            if action == "drag_drop":
                result = await drag_drop(page, kwargs["source"], kwargs["target"], timeout)
                s.touch()
                return result

            if action == "upload_file":
                paths = kwargs.get("file_paths", [])
                if isinstance(paths, str):
                    paths = [paths]
                result = await upload_file(page, kwargs["selector"], paths)
                s.touch()
                return result

            if action == "select_option":
                result = await select_option(
                    page, kwargs["selector"],
                    value=kwargs.get("value", ""),
                    label=kwargs.get("label", ""),
                )
                s.touch()
                return result

            if action == "scroll":
                result = await scroll(
                    page,
                    direction=kwargs.get("direction", "down"),
                    amount=int(kwargs.get("amount", 500)),
                    selector=kwargs.get("selector", ""),
                )
                s.touch()
                return result

            if action == "press_key":
                result = await press_key(page, kwargs["key"], kwargs.get("modifiers", ""))
                s.touch()
                return result

            if action == "get_cookies":
                cookies = await get_cookies(page)
                s.touch()
                return json.dumps(cookies, ensure_ascii=False, default=str)

            if action == "set_cookie":
                result = await set_cookie(page, kwargs.get("cookie", {}))
                s.touch()
                return result

            if action == "get_storage":
                data = await get_storage(page, kwargs.get("type", "local"))
                s.touch()
                return json.dumps(data, ensure_ascii=False, default=str)

            if action == "wait":
                if kwargs.get("url_pattern"):
                    result = await wait_for_navigation(page, kwargs["url_pattern"], timeout)
                else:
                    await page.wait_for_selector(kwargs["selector"], timeout=timeout)
                    result = f"Element found: {kwargs['selector']}"
                s.touch()
                return result

            if action == "back":
                await page.go_back(timeout=timeout)
                title = await page.title()
                s.touch()
                return f"Back to: {page.url}\nTitle: {title}"

            if action == "pdf":
                result = await export_pdf(page, kwargs.get("path", ""))
                s.touch()
                return result

            if action == "evaluate":
                js = kwargs.get("javascript", "")
                if not js:
                    return "[error] javascript required for evaluate"
                result = await page.evaluate(js)
                s.touch()
                return json.dumps(result, ensure_ascii=False, default=str)

            if action == "tabs":
                pages = page.context.pages
                lines = []
                for i, p in enumerate(pages):
                    marker = " (active)" if p == page else ""
                    lines.append(f"  [{i}] {p.url}{marker}")
                s.touch()
                return f"Tabs ({len(pages)}):\n" + "\n".join(lines)

            if action == "new_tab":
                new_page = await self._session_mgr.new_tab(s.id, kwargs.get("url", ""))
                s.page = new_page
                s.touch()
                title = await new_page.title()
                return f"New tab: {new_page.url}\nTitle: {title}"

            if action == "switch_tab":
                idx = int(kwargs.get("index", 0))
                pages = page.context.pages
                if 0 <= idx < len(pages):
                    s.page = pages[idx]
                    await s.page.bring_to_front()
                    title = await s.page.title()
                    s.touch()
                    return f"Switched to tab [{idx}]: {s.page.url}\nTitle: {title}"
                return f"[error] Invalid tab index: {idx}. Tabs: {len(pages)}"

            return (
                f"[error] Unknown action: {action}. Available: click, fill, hover, "
                f"drag_drop, upload_file, select_option, scroll, press_key, "
                f"get_cookies, set_cookie, get_storage, wait, back, pdf, "
                f"evaluate, tabs, new_tab, switch_tab"
            )
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # --- Screenshot ---

    async def screenshot(self, session: str = "", full_page: bool = False, selector: str = "") -> str:
        """Capture screenshot."""
        s = await self._resolve_session_or_create(session)
        page = s.page
        if selector:
            el = await page.query_selector(selector)
            if not el:
                return f"[error] Element not found: {selector}"
            shot = await el.screenshot()
        else:
            shot = await page.screenshot(full_page=full_page)
        encoded = base64.b64encode(shot).decode()
        title = await page.title()
        s.touch()
        return (
            f"Screenshot ({len(shot)} bytes)\n"
            f"URL: {page.url}\nTitle: {title}\n"
            f"Session: {s.name}\n"
            f"[screenshot_base64]{encoded}[/screenshot_base64]"
        )

    # --- Accessibility Tree ---

    async def get_a11y_tree(
        self, session: str = "", interactive_only: bool = False, max_depth: int = 10,
    ) -> str:
        """Extract accessibility tree."""
        s = await self._resolve_session_or_create(session)

        if s.id not in self._a11y_extractors:
            cdp = await get_cdp_session(s.page)
            self._a11y_extractors[s.id] = A11yExtractor(cdp, max_depth=max_depth)

        extractor = self._a11y_extractors[s.id]
        nodes = await extractor.extract()

        if interactive_only:
            nodes = A11yExtractor.filter_interactive(nodes)

        text = A11yExtractor.format_compact(nodes)
        tokens = A11yExtractor.estimate_tokens(text)
        s.touch()
        return f"Accessibility Tree (~{tokens} tokens):\n{text}"

    # --- Network ---

    async def handle_network(self, session: str = "", action: str = "", **kwargs) -> str:
        """Handle network monitoring actions."""
        s = await self._resolve_session_or_create(session)

        if action == "start_capture":
            if s.id not in self._network_monitors:
                cdp = await get_cdp_session(s.page)
                self._network_monitors[s.id] = NetworkMonitor(cdp)
            monitor = self._network_monitors[s.id]
            filters = kwargs.get("url_filters", [])
            await monitor.start_capture(url_filters=filters)
            s.touch()
            return f"Network capture started for session {s.name}"

        if action == "stop_capture":
            monitor = self._network_monitors.get(s.id)
            if not monitor:
                return "[error] No network capture active for this session"
            entries = await monitor.stop_capture()
            summary = monitor.get_summary()
            s.touch()
            lines = [f"Captured {len(entries)} requests:"]
            for e in entries[:50]:  # Show top 50
                lines.append(f"  {e.method} {e.status} {e.url} ({e.duration_ms:.0f}ms)")
            if len(entries) > 50:
                lines.append(f"  ... and {len(entries) - 50} more")
            lines.append(f"Summary: {json.dumps(summary)}")
            return "\n".join(lines)

        if action == "block_urls":
            if s.id not in self._network_monitors:
                cdp = await get_cdp_session(s.page)
                self._network_monitors[s.id] = NetworkMonitor(cdp)
            patterns = kwargs.get("patterns", [])
            await self._network_monitors[s.id].block_urls(patterns)
            s.touch()
            return f"Blocking {len(patterns)} URL patterns"

        if action == "export_har":
            monitor = self._network_monitors.get(s.id)
            if not monitor:
                return "[error] No network data to export"
            har = monitor.export_har()
            s.touch()
            return json.dumps(har, ensure_ascii=False)

        return "[error] Unknown network action. Use: start_capture, stop_capture, block_urls, export_har"

    # --- Tool registration ---

    def get_tool_functions(self) -> list[Callable]:
        """Return tool functions for registration in ToolRegistry."""
        engine = self

        @tool(
            description=(
                "Manage browser sessions. Actions: "
                "create (name, mode=playwright|cdp|user_chrome, persistent=true|false), "
                "list, close (session ID or name), close_all."
            )
        )
        async def browser_session(
            action: str, name: str = "", session: str = "",
            mode: str = "playwright", persistent: bool = False,
            cdp_url: str = "",
        ) -> str:
            return await engine.handle_session(
                action=action, name=name, session=session,
                mode=mode, persistent=persistent, cdp_url=cdp_url,
            )

        @tool(
            description="Navigate to a URL in a browser session."
        )
        async def browser_navigate(
            url: str, session: str = "", wait_until: str = "domcontentloaded",
        ) -> str:
            return await engine.navigate(session=session, url=url, wait_until=wait_until)

        @tool(
            description=(
                "Execute browser action. Actions: click, fill, hover, drag_drop, "
                "upload_file, select_option, scroll, press_key, get_cookies, set_cookie, "
                "get_storage, wait, back, pdf, evaluate, tabs, new_tab, switch_tab. "
                "Pass action-specific params as keyword args."
            )
        )
        async def browser_action(
            action: str, session: str = "", selector: str = "",
            text: str = "", value: str = "", url: str = "",
            javascript: str = "", key: str = "", direction: str = "down",
            amount: int = 500, source: str = "", target: str = "",
            index: int = 0, timeout: int = 10000,
        ) -> str:
            return await engine.do_action(
                session=session, action=action, selector=selector,
                text=text, value=value, url=url, javascript=javascript,
                key=key, direction=direction, amount=amount,
                source=source, target=target, index=index, timeout=timeout,
            )

        @tool(
            description="Capture screenshot of current page or element."
        )
        async def browser_screenshot(
            session: str = "", full_page: bool = False, selector: str = "",
        ) -> str:
            return await engine.screenshot(
                session=session, full_page=full_page, selector=selector,
            )

        @tool(
            description=(
                "Get page accessibility tree — compact text format showing all "
                "interactive elements (buttons, inputs, links). "
                "Set interactive_only=true to filter non-interactive elements."
            )
        )
        async def browser_a11y_tree(
            session: str = "", interactive_only: bool = False, max_depth: int = 10,
        ) -> str:
            return await engine.get_a11y_tree(
                session=session, interactive_only=interactive_only, max_depth=max_depth,
            )

        @tool(
            description=(
                "Browser network monitoring. Actions: "
                "start_capture (begin recording traffic), "
                "stop_capture (return captured requests), "
                "block_urls (block URL patterns for ads/analytics), "
                "export_har (export as HAR JSON)."
            )
        )
        async def browser_network(
            action: str, session: str = "",
            url_filters: str = "", patterns: str = "",
        ) -> str:
            kw: dict[str, Any] = {}
            if url_filters:
                kw["url_filters"] = [f.strip() for f in url_filters.split(",")]
            if patterns:
                kw["patterns"] = [p.strip() for p in patterns.split(",")]
            return await engine.handle_network(
                session=session, action=action, **kw,
            )

        return [
            browser_session,
            browser_navigate,
            browser_action,
            browser_screenshot,
            browser_a11y_tree,
            browser_network,
        ]

    async def cleanup(self) -> None:
        """Cleanup all resources."""
        self._network_monitors.clear()
        self._a11y_extractors.clear()
        await self._session_mgr.close_all()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_browser_engine.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_engine.py tests/tools/test_browser_engine.py
git commit -m "feat(browser): add BrowserEngine unified entry point with 6 tool definitions"
```

---

### Task 8: Wire BrowserEngine into plugin and update plugin.json

**Files:**
- Modify: `src/breadmind/plugins/builtin/browser/plugin.py`
- Modify: `src/breadmind/plugins/builtin/browser/.claude-plugin/plugin.json`

- [ ] **Step 1: Update plugin.py**

Replace contents of `src/breadmind/plugins/builtin/browser/plugin.py`:

```python
"""Web browser automation plugin — exposes BrowserEngine tools."""
from __future__ import annotations

import logging
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin

logger = logging.getLogger(__name__)


class BrowserPlugin(BaseToolPlugin):
    """Plugin providing the browser automation engine."""

    name = "browser"
    version = "0.2.0"

    def __init__(self) -> None:
        self._tools: list[Callable] = []
        self._engine: Any = None

    async def setup(self, container: Any) -> None:
        try:
            from breadmind.tools.browser_engine import BrowserEngine

            # Read config if available
            config = getattr(container, "config", None)
            browser_cfg = getattr(config, "browser", None) if config else None

            kwargs = {}
            if browser_cfg:
                kwargs = {
                    "max_sessions": browser_cfg.max_sessions,
                    "max_tabs": browser_cfg.max_tabs_per_session,
                    "idle_timeout": browser_cfg.idle_timeout_seconds,
                    "headless": browser_cfg.headless,
                    "viewport_width": browser_cfg.viewport_width,
                    "viewport_height": browser_cfg.viewport_height,
                    "locale": browser_cfg.locale,
                    "default_timeout_ms": browser_cfg.default_timeout_ms,
                }

            self._engine = BrowserEngine(**kwargs)
            self._tools = self._engine.get_tool_functions()
            logger.info("BrowserEngine initialized with %d tools", len(self._tools))
        except ImportError:
            logger.warning("Browser engine unavailable (playwright not installed?)")
            # Fallback to legacy single-function tool
            try:
                from breadmind.tools.browser import browser
                self._tools = [browser]
                logger.info("Falling back to legacy browser tool")
            except Exception:
                self._tools = []

    def get_tools(self) -> list[Callable]:
        return self._tools

    async def teardown(self) -> None:
        if self._engine:
            await self._engine.cleanup()
```

- [ ] **Step 2: Update plugin.json version**

Replace `src/breadmind/plugins/builtin/browser/.claude-plugin/plugin.json`:

```json
{
  "name": "browser",
  "version": "0.2.0",
  "description": "Browser automation engine with session management, advanced actions, network monitoring, and accessibility tree",
  "x-breadmind": {
    "priority": 20,
    "enabled_by_default": false,
    "depends_on": [],
    "requires": [],
    "optional_requires": [],
    "python_module": "plugin",
    "safety": { "require_approval": [], "blacklist": [] }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/plugins/builtin/browser/plugin.py src/breadmind/plugins/builtin/browser/.claude-plugin/plugin.json
git commit -m "feat(browser): wire BrowserEngine into plugin with config support and legacy fallback"
```
