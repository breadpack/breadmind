"""PageAnalyzer — combines screenshot + accessibility tree for LLM Vision page analysis."""
from __future__ import annotations

import re
from typing import Any

from breadmind.llm.base import Attachment, LLMMessage, LLMProvider

_SCREENSHOT_RE = re.compile(
    r"\[screenshot_base64\](.*?)\[/screenshot_base64\]", re.DOTALL
)


class PageAnalyzer:
    """Combines screenshot + accessibility tree into a structured LLM Vision analysis request."""

    def __init__(self, llm_provider: LLMProvider, browser_engine: Any) -> None:
        self._llm = llm_provider
        self._engine = browser_engine

    async def analyze_page(
        self,
        session: str,
        question: str | None = None,
        include_network: bool = False,
    ) -> str:
        """Capture screenshot + a11y tree and ask the LLM to analyse the page.

        Returns the LLM's textual analysis.
        """
        screenshot_result: str = await self._engine.screenshot(session)
        a11y_result: str = await self._engine.get_a11y_tree(
            session, interactive_only=True, max_depth=8
        )

        screenshot_b64 = self._extract_screenshot(screenshot_result)

        network_summary: str | None = None
        if include_network:
            try:
                network_summary = await self._engine.get_network_summary(session)
            except Exception:
                network_summary = None

        prompt = self.build_analysis_prompt(
            a11y_tree=a11y_result,
            question=question,
            network_summary=network_summary,
        )

        attachments: list[Attachment] = []
        if screenshot_b64:
            attachments.append(
                Attachment(type="image", data=screenshot_b64, media_type="image/png")
            )

        message = LLMMessage(role="user", content=prompt, attachments=attachments)
        response = await self._llm.chat([message])
        return response.content or ""

    async def find_element(self, session: str, description: str) -> str:
        """Find a specific element on the page by natural-language description.

        Returns the matching accessibility tree entry (e.g. ``[button "Sign In"]``).
        """
        screenshot_result: str = await self._engine.screenshot(session)
        a11y_result: str = await self._engine.get_a11y_tree(
            session, interactive_only=True, max_depth=8
        )

        screenshot_b64 = self._extract_screenshot(screenshot_result)

        prompt = self.build_find_element_prompt(
            a11y_tree=a11y_result,
            description=description,
        )

        attachments: list[Attachment] = []
        if screenshot_b64:
            attachments.append(
                Attachment(type="image", data=screenshot_b64, media_type="image/png")
            )

        message = LLMMessage(role="user", content=prompt, attachments=attachments)
        response = await self._llm.chat([message])
        return response.content or ""

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_screenshot(result: str) -> str | None:
        """Extract the base64 payload from a ``[screenshot_base64]…[/screenshot_base64]`` tag."""
        match = _SCREENSHOT_RE.search(result)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def build_analysis_prompt(
        a11y_tree: str,
        question: str | None,
        network_summary: str | None,
    ) -> str:
        """Build a multi-section vision prompt for general page analysis."""
        sections: list[str] = []

        if question:
            sections.append(f"Question: {question}")
        else:
            sections.append(
                "Describe what you see: page purpose, key interactive elements, current state, "
                "any visible error messages or notifications."
            )

        sections.append(f"Accessibility Tree:\n{a11y_tree}")

        if network_summary:
            sections.append(f"Recent Network Activity:\n{network_summary}")

        sections.append(
            "Using the screenshot and accessibility tree above, provide a clear and concise answer."
        )

        return "\n\n".join(sections)

    @staticmethod
    def build_find_element_prompt(a11y_tree: str, description: str) -> str:
        """Build a prompt asking the LLM to identify a specific element.

        The LLM should return ONLY the matching accessibility tree entry,
        e.g. ``[button "Sign In"]``.
        """
        return (
            f"Find the element that matches this description: {description}\n\n"
            f"Accessibility Tree:\n{a11y_tree}\n\n"
            'Return ONLY the matching accessibility tree entry (e.g., [button "Sign In"]). '
            "Do not include any explanation."
        )
