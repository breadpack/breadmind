"""Action handler that invokes a registered tool by name."""

from __future__ import annotations

from typing import Any

from breadmind.webhook.actions.base import ActionHandler, ActionResult
from breadmind.webhook.models import PipelineAction, PipelineContext


class ToolActionHandler(ActionHandler):
    """Execute a tool from the tool registry.

    Args:
        tool_registry: An object with a ``get_tool(name)`` method that returns
            an async callable tool or ``None`` if not found.
    """

    def __init__(self, tool_registry: Any) -> None:
        self._registry = tool_registry

    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Look up and call the configured tool with its arguments.

        If ``capture_response`` is True and ``response_variable`` is set,
        the tool's output is stored in ``ctx.steps[response_variable]``.
        """
        tool_name: str = action.config.get("tool_name", "")
        arguments: dict[str, Any] = action.config.get("arguments", {})

        tool = self._registry.get_tool(tool_name)
        if tool is None:
            return ActionResult(
                success=False,
                error=f"Tool '{tool_name}' not found in registry",
            )

        try:
            tool_result = await tool(**arguments)

            output = tool_result.output if hasattr(tool_result, "output") else str(tool_result)
            success = tool_result.success if hasattr(tool_result, "success") else True

            if action.capture_response and action.response_variable:
                ctx.steps[action.response_variable] = output

            return ActionResult(success=success, output=output)
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))
