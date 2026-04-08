"""Browser automation tool for BreadMind.

Supports two modes:
  1. CDP — connect to user's existing Chrome (preserves logged-in sessions)
  2. Playwright — launch a headed browser with persistent profile (cookies survive restarts)

Requires:  pip install 'breadmind[browser]'
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy Playwright import — only loaded when a browser tool is actually called
# ---------------------------------------------------------------------------

_playwright_instance = None
_browser = None
_context = None
_page = None


def _default_user_data_dir() -> str:
    """Return platform-specific persistent browser profile directory."""
    import platform
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "breadmind", "browser-profile")
    return os.path.expanduser("~/.config/breadmind/browser-profile")


def _chrome_user_data_dir() -> str | None:
    """Find user's actual Chrome profile directory for session reuse."""
    import platform
    system = platform.system()
    candidates = []
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(os.path.join(local, "Google", "Chrome", "User Data"))
            candidates.append(os.path.join(local, "Microsoft", "Edge", "User Data"))
    elif system == "Darwin":
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, "Library", "Application Support", "Google", "Chrome"))
        candidates.append(os.path.join(home, "Library", "Application Support", "Microsoft Edge"))
    else:
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".config", "google-chrome"))
        candidates.append(os.path.join(home, ".config", "chromium"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


async def _ensure_browser(
    mode: str = "playwright",
    cdp_url: str = "http://localhost:9222",
) -> Any:
    """Ensure browser is running and return the active page."""
    global _playwright_instance, _browser, _context, _page

    if _page is not None and not _page.is_closed():
        return _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright is not installed. Run: pip install 'breadmind[browser]' "
            "then: playwright install chromium"
        )

    if _playwright_instance is None:
        _playwright_instance = await async_playwright().start()

    if mode == "cdp":
        try:
            _browser = await _playwright_instance.chromium.connect_over_cdp(cdp_url)
            contexts = _browser.contexts
            _context = contexts[0] if contexts else await _browser.new_context()
            pages = _context.pages
            _page = pages[0] if pages else await _context.new_page()
        except Exception as e:
            raise RuntimeError(
                f"CDP 연결 실패 ({cdp_url}). Chrome을 다음 옵션으로 실행하세요:\n"
                f"  chrome --remote-debugging-port=9222\n"
                f"오류: {e}"
            )
    elif mode == "user_chrome":
        # Use the user's actual Chrome profile — inherits all logged-in sessions
        chrome_dir = _chrome_user_data_dir()
        if not chrome_dir:
            raise RuntimeError(
                "Chrome 프로필을 찾을 수 없습니다. Chrome이 설치되어 있는지 확인하세요."
            )
        logger.info("Using Chrome profile: %s", chrome_dir)
        # Chrome must be closed to use its profile (lock file conflict)
        # Copy cookies to a temp profile instead
        import shutil
        import tempfile
        temp_dir = os.path.join(tempfile.gettempdir(), "breadmind-chrome-session")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
            # Copy essential files for session reuse
            for name in ("Default", "Profile 1"):
                src = os.path.join(chrome_dir, name)
                dst = os.path.join(temp_dir, name)
                if os.path.isdir(src) and not os.path.exists(dst):
                    try:
                        # Copy only cookie/session files, not the entire profile
                        os.makedirs(dst, exist_ok=True)
                        for fname in ("Cookies", "Login Data", "Web Data", "Preferences", "Secure Preferences"):
                            sf = os.path.join(src, fname)
                            if os.path.isfile(sf):
                                shutil.copy2(sf, dst)
                    except Exception:
                        pass
            # Copy Local State
            local_state = os.path.join(chrome_dir, "Local State")
            if os.path.isfile(local_state):
                try:
                    shutil.copy2(local_state, temp_dir)
                except Exception:
                    pass
        _context = await _playwright_instance.chromium.launch_persistent_context(
            temp_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        _page = _context.pages[0] if _context.pages else await _context.new_page()
    else:
        user_data_dir = _default_user_data_dir()
        os.makedirs(user_data_dir, exist_ok=True)
        _context = await _playwright_instance.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        _page = _context.pages[0] if _context.pages else await _context.new_page()

    return _page


async def _close_browser() -> None:
    """Cleanup browser resources."""
    global _playwright_instance, _browser, _context, _page
    try:
        if _context:
            await _context.close()
    except Exception:
        pass
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright_instance:
            await _playwright_instance.stop()
    except Exception:
        pass
    _playwright_instance = _browser = _context = _page = None


async def get_cdp_session(page) -> Any:
    """Get CDP session from a Playwright page for direct protocol access."""
    return await page.context.new_cdp_session(page)


def get_active_page() -> Any | None:
    """Return the current active page, or None."""
    return _page


def get_active_context() -> Any | None:
    """Return the current browser context, or None."""
    return _context


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Control a web browser. Actions: "
        "navigate (go to URL), "
        "click (click element by selector or text), "
        "fill (type text into input field), "
        "screenshot (capture current page), "
        "get_text (extract text content), "
        "get_html (get page HTML), "
        "evaluate (run JavaScript), "
        "wait (wait for selector), "
        "back (go back), "
        "close (close browser). "
        "Set mode='user_chrome' to use user's Chrome profile with logged-in sessions "
        "(Google, Notion, GitHub etc. — no API key needed). "
        "Set mode='cdp' to connect to running Chrome with remote debugging. "
        "Default mode='playwright' launches a clean persistent browser."
    )
)
async def browser(
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    value: str = "",
    javascript: str = "",
    mode: str = "playwright",
    cdp_url: str = "http://localhost:9222",
    timeout: int = 10000,
) -> str:
    """Browser automation supporting CDP and Playwright modes."""
    if action == "close":
        await _close_browser()
        return "Browser closed."

    try:
        page = await _ensure_browser(mode=mode, cdp_url=cdp_url)
    except RuntimeError as e:
        return f"[error] {e}"

    try:
        if action == "navigate":
            if not url:
                return "[error] url is required for navigate action"
            resp = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            title = await page.title()
            return f"Navigated to: {page.url}\nTitle: {title}\nStatus: {resp.status if resp else 'unknown'}"

        elif action == "click":
            target = selector or text
            if not target:
                return "[error] selector or text is required for click action"
            if selector:
                await page.click(selector, timeout=timeout)
            else:
                await page.get_by_text(text, exact=False).first.click(timeout=timeout)
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return f"Clicked: {target}\nCurrent URL: {page.url}"

        elif action == "fill":
            if not selector:
                return "[error] selector is required for fill action"
            await page.fill(selector, value, timeout=timeout)
            return f"Filled '{selector}' with value (length={len(value)})"

        elif action == "screenshot":
            screenshot_bytes = await page.screenshot(full_page=False)
            encoded = base64.b64encode(screenshot_bytes).decode()
            title = await page.title()
            return (
                f"Screenshot captured ({len(screenshot_bytes)} bytes)\n"
                f"URL: {page.url}\nTitle: {title}\n"
                f"[screenshot_base64]{encoded}[/screenshot_base64]"
            )

        elif action == "get_text":
            if selector:
                element = await page.query_selector(selector)
                if element:
                    content = await element.text_content()
                else:
                    content = f"Element not found: {selector}"
            else:
                content = await page.inner_text("body")
            # Truncate very long text
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            return content

        elif action == "get_html":
            if selector:
                element = await page.query_selector(selector)
                if element:
                    content = await element.inner_html()
                else:
                    content = f"Element not found: {selector}"
            else:
                content = await page.content()
            if len(content) > 20000:
                content = content[:20000] + "\n... (truncated)"
            return content

        elif action == "evaluate":
            if not javascript:
                return "[error] javascript is required for evaluate action"
            result = await page.evaluate(javascript)
            return json.dumps(result, ensure_ascii=False, default=str)

        elif action == "wait":
            if not selector:
                return "[error] selector is required for wait action"
            await page.wait_for_selector(selector, timeout=timeout)
            return f"Element found: {selector}"

        elif action == "back":
            await page.go_back(timeout=timeout)
            title = await page.title()
            return f"Navigated back to: {page.url}\nTitle: {title}"

        elif action == "tabs":
            pages = page.context.pages
            lines = []
            for i, p in enumerate(pages):
                marker = " (active)" if p == page else ""
                lines.append(f"  [{i}] {p.url}{marker}")
            return f"Open tabs ({len(pages)}):\n" + "\n".join(lines)

        elif action == "switch_tab":
            idx = int(value) if value else 0
            pages = page.context.pages
            if 0 <= idx < len(pages):
                global _page
                _page = pages[idx]
                await _page.bring_to_front()
                title = await _page.title()
                return f"Switched to tab [{idx}]: {_page.url}\nTitle: {title}"
            return f"[error] Invalid tab index: {idx}. Open tabs: {len(pages)}"

        elif action == "new_tab":
            _page = await page.context.new_page()
            if url:
                await _page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            title = await _page.title()
            return f"New tab opened: {_page.url}\nTitle: {title}"

        else:
            return (
                f"[error] Unknown action: {action}. "
                f"Available: navigate, click, fill, screenshot, get_text, get_html, "
                f"evaluate, wait, back, tabs, switch_tab, new_tab, close"
            )

    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def register_browser_tools(registry) -> None:
    """Register browser tools into the given ToolRegistry."""
    registry.register(browser)
