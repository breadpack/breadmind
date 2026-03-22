"""Web browser automation tool plugin (Playwright/CDP)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin

logger = logging.getLogger(__name__)


class BrowserPlugin(BaseToolPlugin):
    """Plugin providing the browser automation tool."""

    name = "browser"
    version = "0.1.0"

    def __init__(self) -> None:
        self._tools: list[Callable] = []

    async def setup(self, container: Any) -> None:
        try:
            from breadmind.tools.browser import browser
            self._tools = [browser]
        except Exception:
            logger.warning("Browser tool unavailable (playwright not installed?)")
            self._tools = []

    def get_tools(self) -> list[Callable]:
        return self._tools
