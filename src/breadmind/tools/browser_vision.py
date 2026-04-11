"""High-level vision-based browser tools — natural language element interaction."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

_A11Y_ELEMENT_RE = re.compile(r'\[(\w+)\s+"([^"]+)"')


class VisionBrowser:
    def __init__(self, page_analyzer: Any, browser_engine: Any) -> None:
        self._analyzer = page_analyzer
        self._engine = browser_engine

    async def analyze(self, session: str = "", question: str = "") -> str:
        return await self._analyzer.analyze_page(session=session, question=question)

    async def find_element(self, session: str = "", description: str = "") -> str:
        return await self._analyzer.find_element(session=session, description=description)

    async def smart_click(self, session: str = "", description: str = "") -> str:
        element_info = await self._analyzer.find_element(session=session, description=description)
        selector = self._extract_selector(element_info)
        if not selector:
            return f"[error] Could not identify element for: {description}\nLLM response: {element_info}"
        click_result = await self._engine.do_action(session=session, action="click", text=selector)
        return f"Found: {element_info}\nAction: {click_result}"

    async def smart_fill(self, session: str = "", description: str = "", value: str = "") -> str:
        element_info = await self._analyzer.find_element(session=session, description=description)
        selector = self._extract_selector(element_info)
        if not selector:
            return f"[error] Could not identify input for: {description}\nLLM response: {element_info}"
        await self._engine.do_action(session=session, action="click", text=selector)
        fill_result = await self._engine.do_action(session=session, action="fill", selector="*:focus", value=value)
        return f"Found: {element_info}\nFilled with: {value}\nResult: {fill_result}"

    @staticmethod
    def _extract_selector(element_info: str) -> str:
        match = _A11Y_ELEMENT_RE.search(element_info)
        if match:
            return match.group(2)
        css_match = re.search(r'(?:selector|css):\s*`?([^`\n]+)`?', element_info, re.IGNORECASE)
        if css_match:
            return css_match.group(1).strip()
        clean = element_info.strip()
        if len(clean) < 100:
            return clean
        return ""

    def get_tool_functions(self) -> list[Callable]:
        vb = self

        @tool(description="Analyze current web page using AI Vision. Captures screenshot + accessibility tree, sends to LLM, returns detailed page description.")
        async def browser_analyze(session: str = "", question: str = "") -> str:
            return await vb.analyze(session=session, question=question)

        @tool(description="Find a web page element by natural language description using AI Vision. Example: 'the login button', 'email input field'")
        async def browser_find_element(session: str = "", description: str = "") -> str:
            return await vb.find_element(session=session, description=description)

        @tool(description="Find element by description using AI Vision and click it. Example: description='the Sign In button'")
        async def browser_smart_click(session: str = "", description: str = "") -> str:
            return await vb.smart_click(session=session, description=description)

        @tool(description="Find input field by description using AI Vision and fill it with a value. Example: description='email field', value='user@example.com'")
        async def browser_smart_fill(session: str = "", description: str = "", value: str = "") -> str:
            return await vb.smart_fill(session=session, description=description, value=value)

        return [browser_analyze, browser_find_element, browser_smart_click, browser_smart_fill]
