"""Action handler that sends messages to the BreadMind agent."""

from __future__ import annotations

from typing import Any, Callable

from breadmind.webhook.actions.base import ActionHandler, ActionResult, resolve_template
from breadmind.webhook.models import PipelineAction, PipelineContext


class AgentActionHandler(ActionHandler):
    """Send a rendered message to the agent and optionally capture its response.

    Args:
        message_handler: An async callable that accepts ``(message, user=..., channel=...)``
            and returns the agent's response string.
    """

    def __init__(self, message_handler: Callable[..., Any]) -> None:
        self._message_handler = message_handler

    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Render the message template and call the agent handler.

        If ``capture_response`` is True and ``response_variable`` is set,
        the response is stored in ``ctx.steps[response_variable]``.
        """
        try:
            message_template: str = action.config.get("message_template", "")
            message = resolve_template(message_template, ctx)

            channel = f"webhook:{ctx.endpoint}"
            response = await self._message_handler(
                message,
                user="webhook-pipeline",
                channel=channel,
            )

            if action.capture_response and action.response_variable:
                ctx.steps[action.response_variable] = response

            return ActionResult(success=True, output=str(response) if response is not None else "")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))
