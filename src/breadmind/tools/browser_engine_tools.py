"""Tool function factory for BrowserEngine.

Defines the 6 LLM-callable tool functions that wrap the BrowserEngine methods.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from breadmind.tools.registry import tool

if TYPE_CHECKING:
    from breadmind.tools.browser_engine import BrowserEngine


def build_tool_functions(engine: "BrowserEngine") -> list[Callable]:
    """Create and return the 6 tool-decorated functions for LLM tool-calling.

    Each function captures *engine* via closure and delegates to the
    corresponding BrowserEngine method.
    """

    @tool(description=(
        "Manage browser sessions. "
        "action=create: create a new session (name, mode=playwright|cdp, persistent=false, cdp_url). "
        "action=list: list all active sessions. "
        "action=close: close a session by id or name (session). "
        "action=close_all: close all sessions."
    ))
    async def browser_session(
        action: str,
        name: str = "",
        session: str = "",
        mode: str = "playwright",
        persistent: bool = False,
        cdp_url: str = "",
    ) -> str:
        return await engine.handle_session(
            action=action, name=name, session=session,
            mode=mode, persistent=persistent, cdp_url=cdp_url,
        )

    @tool(description=(
        "Navigate the browser to a URL. "
        "url: the target URL. "
        "session: session id or name (optional, uses most recent if omitted). "
        "wait_until: domcontentloaded|load|networkidle (default: domcontentloaded)."
    ))
    async def browser_navigate(
        url: str,
        session: str = "",
        wait_until: str = "domcontentloaded",
    ) -> str:
        return await engine.navigate(session=session, url=url, wait_until=wait_until)

    @tool(description=(
        "Perform a browser action. "
        "action: click, fill, hover, drag_drop, upload_file, select_option, scroll, "
        "press_key, get_cookies, set_cookie, get_storage, wait, back, pdf, evaluate, "
        "tabs, new_tab, switch_tab. "
        "selector: CSS/XPath selector. text: visible text for click. "
        "value: text value / JSON cookie / storage type. "
        "javascript: JS code for evaluate. key: key name for press_key. "
        "direction: scroll direction (down/up/left/right). amount: scroll pixels. "
        "source/target: selectors for drag_drop. index: tab index for switch_tab."
    ))
    async def browser_action(
        action: str,
        session: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        url: str = "",
        javascript: str = "",
        key: str = "",
        direction: str = "down",
        amount: int = 500,
        source: str = "",
        target: str = "",
        index: int = 0,
        timeout: int = 10000,
    ) -> str:
        return await engine.do_action(
            session=session, action=action,
            selector=selector, text=text, value=value, url=url,
            javascript=javascript, key=key, direction=direction,
            amount=amount, source=source, target=target,
            index=index, timeout=timeout,
        )

    @tool(description=(
        "Capture a screenshot of the current browser page. "
        "session: session id or name (optional). "
        "full_page: capture the full scrollable page (default: false). "
        "selector: CSS selector to screenshot a specific element (optional)."
    ))
    async def browser_screenshot(
        session: str = "",
        full_page: bool = False,
        selector: str = "",
    ) -> str:
        return await engine.screenshot(session=session, full_page=full_page, selector=selector)

    @tool(description=(
        "Extract the accessibility tree from the current page. "
        "session: session id or name (optional). "
        "interactive_only: return only interactive elements like buttons and inputs (default: false). "
        "max_depth: maximum tree depth to extract (default: 10)."
    ))
    async def browser_a11y_tree(
        session: str = "",
        interactive_only: bool = False,
        max_depth: int = 10,
    ) -> str:
        return await engine.get_a11y_tree(
            session=session, interactive_only=interactive_only, max_depth=max_depth
        )

    @tool(description=(
        "Manage network monitoring for a browser session. "
        "action=start_capture: begin capturing network requests (url_filters: comma-separated substrings). "
        "action=stop_capture: stop capture and return summary. "
        "action=block_urls: block requests matching patterns (patterns: comma-separated). "
        "action=export_har: export captured traffic as HAR JSON. "
        "session: session id or name (optional)."
    ))
    async def browser_network(
        action: str,
        session: str = "",
        url_filters: str = "",
        patterns: str = "",
    ) -> str:
        return await engine.handle_network(
            session=session, action=action,
            url_filters=url_filters, patterns=patterns,
        )

    return [
        browser_session,
        browser_navigate,
        browser_action,
        browser_screenshot,
        browser_a11y_tree,
        browser_network,
    ]
