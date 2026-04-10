"""Action handler: processes user actions from the SDUI renderer.

Action message shape:
    {"kind": "intervention", "flow_id": ..., "step_id": ..., "value": ...}
    {"kind": "chat_input", "session_id": ..., "values": {"text": ...}}
    {"kind": "view_request", "view_key": ..., "params": ...}  # handled in ws route directly
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent


class ActionHandler:
    """Dispatch SDUI action messages to the appropriate flow-event emission.

    The handler is intentionally thin: Phase 1 only needs to translate user
    interventions into :class:`FlowEvent` publications on the
    :class:`FlowEventBus`. Navigation (``view_request``) is handled directly
    by the WebSocket route, and chat input is deferred to the chat handler
    integration planned for Task 22.
    """

    def __init__(self, bus: FlowEventBus) -> None:
        self._bus = bus

    async def handle(self, action: dict[str, Any], *, user_id: str) -> dict[str, Any]:
        kind = action.get("kind")
        if kind == "intervention":
            return await self._intervention(action, user_id)
        if kind == "view_request":
            # The WS route handles navigation directly; this is a no-op for completeness.
            return {
                "ok": True,
                "view_key": action.get("view_key"),
                "params": action.get("params", {}),
            }
        if kind == "chat_input":
            # Phase 1: defer to chat handler integration (Task 22).
            return {"ok": True, "deferred": "chat_handler"}
        return {"ok": False, "error": f"unknown action kind: {kind}"}

    async def _intervention(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        try:
            flow_id = UUID(str(action["flow_id"]))
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "error": "invalid or missing flow_id"}
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.USER_INTERVENTION,
                payload={
                    "step_id": action.get("step_id"),
                    "action": action.get("value"),
                    "user_id": user_id,
                    "metadata": action.get("metadata", {}),
                },
                actor=FlowActor.USER,
            )
        )
        return {"ok": True}
