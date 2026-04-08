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
            # Initialize vision layer if LLM provider is available
            llm_provider = None
            try:
                llm_provider = container.get("llm_provider")
            except Exception:
                llm_provider = getattr(container, "llm_provider", None)
            if llm_provider:
                self._engine.init_vision(llm_provider)
                logger.info("Browser vision layer initialized")
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
