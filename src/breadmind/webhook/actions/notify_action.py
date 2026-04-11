"""Action handler that routes notifications via a message router."""

from __future__ import annotations

from typing import Any

from breadmind.webhook.actions.base import ActionHandler, ActionResult
from breadmind.webhook.models import PipelineAction, PipelineContext


class NotifyActionHandler(ActionHandler):
    """Send a notification through the configured message router.

    Args:
        message_router: An object with an async ``send_to_channel(channel, target, message)``
            method.

    Config keys:
        channel (str): Router channel identifier (e.g. ``"slack"``).
        target (str): Destination within the channel (e.g. ``"#devops"``).
        message (str): Message text to send.
    """

    def __init__(self, message_router: Any) -> None:
        self._router = message_router

    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Send the notification to the specified channel and target."""
        try:
            channel: str = action.config.get("channel", "")
            target: str = action.config.get("target", "")
            message: str = action.config.get("message", "")

            await self._router.send_to_channel(channel, target, message)

            return ActionResult(success=True, output=f"Notified {channel}:{target}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))
