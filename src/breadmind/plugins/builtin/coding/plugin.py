"""Code delegation tool plugin for external coding agents."""

from __future__ import annotations

import logging
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin

logger = logging.getLogger(__name__)


class CodingPlugin(BaseToolPlugin):
    """Plugin providing the code_delegate tool."""

    name = "coding"
    version = "0.1.0"

    def __init__(self) -> None:
        self._tools: list[Callable] = []

    async def setup(self, container: Any) -> None:
        db = container.get_optional("db")
        provider = container.get_optional("llm_provider")

        from breadmind.coding.tool import create_code_delegate_tool
        from breadmind.llm.base import ToolDefinition

        tool_def_dict, handler = create_code_delegate_tool(db=db, provider=provider)
        handler._tool_definition = ToolDefinition(
            name=tool_def_dict["name"],
            description=tool_def_dict["description"],
            parameters=tool_def_dict["parameters"],
        )
        self._tools = [handler]

    def get_tools(self) -> list[Callable]:
        return self._tools
