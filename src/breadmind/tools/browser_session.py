"""Browser session management for BreadMind.

Provides BrowserSession dataclass and SessionManager for managing
multiple named browser sessions with lifecycle, idle cleanup, and tab limits.
"""
from __future__ import annotations

import logging
import os
import platform
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Headless detection helpers
# ---------------------------------------------------------------------------


def _detect_headless() -> bool:
    """Auto-detect whether to run headless based on display environment."""
    system = platform.system()
    if system == "Linux":
        return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if system == "Windows":
        # Windows almost always has a GUI
        return False
    # macOS default
    return False


def resolve_headless(config_value: str | bool | None) -> bool:
    """Resolve headless setting from config value.

    Args:
        config_value: "true", "false", "auto", True, False, or None.

    Returns:
        bool — whether to run headless.
    """
    if isinstance(config_value, bool):
        return config_value
    if config_value is None or str(config_value).lower() == "auto":
        return _detect_headless()
    return str(config_value).lower() == "true"


# ---------------------------------------------------------------------------
# BrowserSession dataclass
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    """Holds all state for a single named browser session."""

    id: str
    name: str
    mode: str  # "playwright" | "cdp"
    persistent: bool
    context: Any  # playwright BrowserContext
    page: Any     # playwright Page
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    tabs: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last_active timestamp to now."""
        self.last_active = time.time()

    def is_idle(self, timeout: float) -> bool:
        """Return True if session has been inactive longer than *timeout* seconds.

        Persistent sessions are never considered idle.
        """
        if self.persistent:
            return False
        return (time.time() - self.last_active) > timeout

    def to_dict(self) -> dict[str, Any]:
        """Serialize session metadata (no Playwright objects)."""
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "persistent": self.persistent,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "tab_count": len(self.tabs),
        }


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages a pool of named browser sessions.

    Enforces max_sessions and max_tabs limits, handles idle cleanup,
    and lazily initialises Playwright on first use.
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
    ) -> None:
        self.max_sessions = max_sessions
        self.max_tabs = max_tabs
        self.idle_timeout = idle_timeout
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.locale = locale

        self._sessions: dict[str, BrowserSession] = {}
        self._playwright: Any = None
        self._browser: Any = None

    # ------------------------------------------------------------------
    # Internal: Playwright lifecycle
    # ------------------------------------------------------------------

    async def _ensure_playwright(self) -> Any:
        """Lazily start async_playwright."""
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise RuntimeError(
                    "playwright is not installed. "
                    "Run: pip install 'breadmind[browser]' && playwright install chromium"
                )
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_browser(self) -> Any:
        """Lazily launch chromium browser."""
        if self._browser is None:
            pw = await self._ensure_playwright()
            headless = resolve_headless(self.headless)
            self._browser = await pw.chromium.launch(headless=headless)
            logger.info("Launched chromium (headless=%s)", headless)
        return self._browser

    async def _launch_context(
        self,
        mode: str = "playwright",
        cdp_url: str = "http://localhost:9222",
    ) -> tuple[Any, Any]:
        """Create a new BrowserContext and return (context, page).

        For cdp mode, connects to an existing Chrome instance.
        For playwright mode, creates a fresh context via the managed browser.
        """
        pw = await self._ensure_playwright()

        if mode == "cdp":
            try:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
                contexts = browser.contexts
                ctx = contexts[0] if contexts else await browser.new_context()
                pages = ctx.pages
                page = pages[0] if pages else await ctx.new_page()
            except Exception as exc:
                raise RuntimeError(
                    f"CDP 연결 실패 ({cdp_url}). "
                    f"Chrome을 --remote-debugging-port=9222 로 실행하세요.\n오류: {exc}"
                ) from exc
        else:
            browser = await self._ensure_browser()
            ctx = await browser.new_context(
                viewport={"width": self.viewport_width, "height": self.viewport_height},
                locale=self.locale,
            )
            page = await ctx.new_page()

        return ctx, page

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        mode: str = "playwright",
        persistent: bool = False,
        cdp_url: str = "http://localhost:9222",
    ) -> BrowserSession:
        """Create and register a new browser session.

        Raises RuntimeError if max_sessions would be exceeded.
        """
        if len(self._sessions) >= self.max_sessions:
            raise RuntimeError(
                f"Maximum sessions ({self.max_sessions}) reached. "
                "Close an existing session before creating a new one."
            )

        ctx, page = await self._launch_context(mode=mode, cdp_url=cdp_url)
        session_id = uuid.uuid4().hex[:8]

        session = BrowserSession(
            id=session_id,
            name=name,
            mode=mode,
            persistent=persistent,
            context=ctx,
            page=page,
        )
        self._sessions[session_id] = session
        logger.info("Created session '%s' (id=%s, mode=%s)", name, session_id, mode)
        return session

    def get(self, session_id: str) -> BrowserSession | None:
        """Return session by ID, updating last_active. None if not found."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.touch()
        return session

    def get_by_name(self, name: str) -> BrowserSession | None:
        """Return the first session matching *name*, updating last_active."""
        for session in self._sessions.values():
            if session.name == name:
                session.touch()
                return session
        return None

    def get_most_recent(self) -> BrowserSession | None:
        """Return the session with the most recent last_active, updating it."""
        if not self._sessions:
            return None
        session = max(self._sessions.values(), key=lambda s: s.last_active)
        session.touch()
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return serialised metadata for all sessions."""
        return [s.to_dict() for s in self._sessions.values()]

    async def close(self, session_id: str) -> None:
        """Close and remove session by ID."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            await session.context.close()
        except Exception as exc:
            logger.warning("Error closing context for session %s: %s", session_id, exc)
        logger.info("Closed session '%s' (id=%s)", session.name, session_id)

    async def close_all(self) -> None:
        """Close all sessions, then the browser and playwright instances."""
        for session_id in list(self._sessions.keys()):
            await self.close(session_id)
        try:
            if self._browser:
                await self._browser.close()
        except Exception as exc:
            logger.warning("Error closing browser: %s", exc)
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("Error stopping playwright: %s", exc)
        self._browser = None
        self._playwright = None

    async def cleanup_idle(self) -> list[str]:
        """Close transient sessions that have exceeded idle_timeout.

        Returns:
            List of session IDs that were removed.
        """
        removed: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if session.is_idle(timeout=self.idle_timeout):
                logger.info(
                    "Closing idle session '%s' (id=%s, inactive=%.0fs)",
                    session.name,
                    session_id,
                    time.time() - session.last_active,
                )
                await self.close(session_id)
                removed.append(session_id)
        return removed

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    async def new_tab(
        self,
        session_id: str,
        url: str = "",
        timeout: int = 30_000,
    ) -> Any:
        """Open a new tab in the given session, optionally navigating to *url*.

        Raises RuntimeError if max_tabs would be exceeded.
        Returns the new Playwright Page.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        total_tabs = len(session.tabs) + 1  # +1 for the main page
        if total_tabs >= self.max_tabs:
            raise RuntimeError(
                f"Maximum tabs ({self.max_tabs}) reached for session '{session.name}'."
            )

        new_page = await session.context.new_page()
        tab_id = uuid.uuid4().hex[:6]
        session.tabs[tab_id] = new_page
        session.touch()

        if url:
            await new_page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            logger.info("New tab %s navigated to %s", tab_id, url)

        return new_page
