"""Unified browser engine — entry point for all browser operations."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Callable

from breadmind.tools.browser import get_cdp_session
from breadmind.tools.browser_session import SessionManager, BrowserSession
from breadmind.tools.browser_a11y import A11yExtractor
from breadmind.tools.browser_network import NetworkMonitor
from breadmind.tools.browser_engine_actions import dispatch_action
from breadmind.tools.browser_engine_tools import build_tool_functions

logger = logging.getLogger(__name__)


class BrowserEngine:
    """Orchestrates SessionManager, ActionsHandler, NetworkMonitor, and A11yExtractor.

    Exposes 6 tool functions for LLM tool-calling via get_tool_functions().
    """

    def __init__(
        self,
        max_sessions: int = 5,
        max_tabs: int = 20,
        idle_timeout: float = 300,
        headless: str | bool = "auto",
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
        self._network_monitors: dict[str, NetworkMonitor] = {}
        self._a11y_extractors: dict[str, A11yExtractor] = {}
        self._default_timeout = default_timeout_ms

    # ------------------------------------------------------------------
    # Session resolution helpers
    # ------------------------------------------------------------------

    def _resolve_session(self, session: str) -> BrowserSession | None:
        """Try to find a session by ID first, then by name."""
        found = self._session_mgr.get(session)
        if found is not None:
            return found
        return self._session_mgr.get_by_name(session)

    async def _resolve_session_or_create(self, session: str) -> BrowserSession:
        """Resolve session by ID/name, fall back to most recent, or create transient."""
        if session:
            found = self._resolve_session(session)
            if found is not None:
                return found

        recent = self._session_mgr.get_most_recent()
        if recent is not None:
            return recent

        name = session or "transient"
        return await self._session_mgr.create(name=name, mode="playwright", persistent=False)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def handle_session(
        self,
        action: str,
        name: str = "",
        session: str = "",
        mode: str = "playwright",
        persistent: bool = False,
        cdp_url: str = "",
    ) -> str:
        """Create, list, close, or close_all browser sessions."""
        if action == "create":
            try:
                kwargs: dict[str, Any] = {
                    "name": name or "default",
                    "mode": mode,
                    "persistent": persistent,
                }
                if cdp_url:
                    kwargs["cdp_url"] = cdp_url
                new_session = await self._session_mgr.create(**kwargs)
                return (
                    f"Created session '{new_session.name}' "
                    f"(id={new_session.id}, mode={new_session.mode})"
                )
            except RuntimeError as e:
                return f"[error] {e}"

        if action == "list":
            sessions = self._session_mgr.list_sessions()
            if not sessions:
                return "No active sessions."
            lines = ["Active sessions:"]
            for s in sessions:
                lines.append(
                    f"  [{s['id']}] {s['name']} — mode={s['mode']} "
                    f"persistent={s['persistent']} tabs={s['tab_count']}"
                )
            return "\n".join(lines)

        if action == "close":
            if not session:
                return "[error] session (id or name) is required for close action"
            found = self._resolve_session(session)
            if found is None:
                return f"[error] Session not found: {session}"
            sid = found.id
            sname = found.name
            await self._session_mgr.close(sid)
            self._network_monitors.pop(sid, None)
            self._a11y_extractors.pop(sid, None)
            return f"Closed session '{sname}' (id={sid})"

        if action == "close_all":
            await self._session_mgr.close_all()
            self._network_monitors.clear()
            self._a11y_extractors.clear()
            return "All sessions closed."

        return (
            f"[error] Unknown action: {action}. "
            "Available: create, list, close, close_all"
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate(
        self,
        session: str = "",
        url: str = "",
        wait_until: str = "domcontentloaded",
    ) -> str:
        """Navigate a session's page to a URL."""
        if not url:
            return "[error] url is required"
        try:
            sess = await self._resolve_session_or_create(session)
            page = sess.page
            resp = await page.goto(url, wait_until=wait_until, timeout=self._default_timeout)
            title = await page.title()
            status = resp.status if resp else "unknown"
            sess.touch()
            return (
                f"Navigated to: {page.url}\n"
                f"Title: {title}\n"
                f"Status: {status}\n"
                f"Session: {sess.name} (id={sess.id})"
            )
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Actions dispatcher
    # ------------------------------------------------------------------

    async def do_action(self, session: str = "", action: str = "", **kwargs: Any) -> str:
        """Dispatch browser actions to the appropriate handler functions."""
        if not action:
            return "[error] action is required"
        try:
            sess = await self._resolve_session_or_create(session)
            result = await dispatch_action(
                sess=sess,
                session_mgr=self._session_mgr,
                action=action,
                default_timeout=self._default_timeout,
                **kwargs,
            )
            sess.touch()
            return result
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def screenshot(
        self,
        session: str = "",
        full_page: bool = False,
        selector: str = "",
    ) -> str:
        """Capture a screenshot of the current page or a specific element."""
        try:
            sess = await self._resolve_session_or_create(session)
            page = sess.page

            if selector:
                element = await page.query_selector(selector)
                if element is None:
                    return f"[error] Element not found: {selector}"
                screenshot_bytes = await element.screenshot()
            else:
                screenshot_bytes = await page.screenshot(full_page=full_page)

            encoded = base64.b64encode(screenshot_bytes).decode("ascii")
            title = await page.title()
            sess.touch()
            return (
                f"Screenshot captured ({len(screenshot_bytes)} bytes)\n"
                f"URL: {page.url}\nTitle: {title}\n"
                f"[screenshot_base64]{encoded}[/screenshot_base64]"
            )
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Accessibility tree
    # ------------------------------------------------------------------

    async def get_a11y_tree(
        self,
        session: str = "",
        interactive_only: bool = False,
        max_depth: int = 10,
    ) -> str:
        """Extract and return the accessibility tree for the current page."""
        try:
            sess = await self._resolve_session_or_create(session)
            page = sess.page

            cdp = await get_cdp_session(page)
            extractor = A11yExtractor(cdp, max_depth=max_depth)
            nodes = await extractor.extract()

            if interactive_only:
                nodes = A11yExtractor.filter_interactive(nodes)

            text = A11yExtractor.format_compact(nodes)
            token_estimate = A11yExtractor.estimate_tokens(text)
            sess.touch()
            return (
                f"Accessibility tree (session={sess.name}, ~{token_estimate} tokens):\n{text}"
            )
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Network monitoring
    # ------------------------------------------------------------------

    async def handle_network(
        self,
        session: str = "",
        action: str = "",
        **kwargs: Any,
    ) -> str:
        """Start/stop network capture, block URLs, or export HAR."""
        if not action:
            return "[error] action is required"
        try:
            sess = await self._resolve_session_or_create(session)
            sid = sess.id
            page = sess.page

            if action == "start_capture":
                cdp = await get_cdp_session(page)
                monitor = NetworkMonitor(cdp)
                url_filters_raw = kwargs.get("url_filters", "")
                url_filters = (
                    [f.strip() for f in url_filters_raw.split(",") if f.strip()]
                    if url_filters_raw else None
                )
                await monitor.start_capture(url_filters=url_filters)
                self._network_monitors[sid] = monitor
                sess.touch()
                return f"Network capture started for session '{sess.name}'"

            if action == "stop_capture":
                monitor = self._network_monitors.get(sid)
                if monitor is None:
                    return "[error] No active capture for this session"
                entries = await monitor.stop_capture()
                del self._network_monitors[sid]
                summary = monitor.get_summary()
                sess.touch()
                return (
                    f"Network capture stopped. Captured {len(entries)} requests.\n"
                    f"Summary: {json.dumps(summary, default=str)}"
                )

            if action == "block_urls":
                patterns_raw = kwargs.get("patterns", "")
                patterns = [p.strip() for p in patterns_raw.split(",") if p.strip()]
                if not patterns:
                    return "[error] patterns required for block_urls"
                cdp = await get_cdp_session(page)
                monitor = self._network_monitors.get(sid) or NetworkMonitor(cdp)
                await monitor.block_urls(patterns)
                sess.touch()
                return f"Blocking {len(patterns)} URL pattern(s): {patterns}"

            if action == "export_har":
                monitor = self._network_monitors.get(sid)
                if monitor is None:
                    return "[error] No active capture for this session"
                har = monitor.export_har()
                sess.touch()
                return json.dumps(har, default=str)

            return (
                f"[error] Unknown action: {action}. "
                "Available: start_capture, stop_capture, block_urls, export_har"
            )

        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Tool function factory
    # ------------------------------------------------------------------

    def get_tool_functions(self) -> list[Callable]:
        """Return 6 tool-decorated functions for LLM tool-calling."""
        return build_tool_functions(self)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """Release all resources: monitors, extractors, and sessions."""
        self._network_monitors.clear()
        self._a11y_extractors.clear()
        await self._session_mgr.close_all()
