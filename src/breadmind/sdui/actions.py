"""Action handler: processes user actions from the SDUI renderer.

Action message shape:
    {"kind": "intervention", "flow_id": ..., "step_id": ..., "value": ...}
    {"kind": "chat_input", "session_id": ..., "values": {"text": ...}}
    {"kind": "view_request", "view_key": ..., "params": ...}  # handled in ws route directly
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable
from uuid import UUID

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)


MessageHandler = Callable[..., Awaitable[str]]


class ActionHandler:
    """Dispatch SDUI action messages to the appropriate handler.

    Phase 1 only handled :class:`FlowEvent` interventions. Phase 1.5 adds
    chat input: when a ``message_handler`` and ``working_memory`` are
    provided, ``chat_input`` actions are forwarded to the CoreAgent via
    the message handler. The working memory is used by the chat view
    (not directly by this handler) to render the updated conversation.
    """

    def __init__(
        self,
        bus: FlowEventBus,
        *,
        message_handler: MessageHandler | None = None,
        working_memory: Any = None,
    ) -> None:
        self._bus = bus
        self._message_handler = message_handler
        self._working_memory = working_memory

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
            return await self._chat_input(action, user_id)
        if kind == "dev_inject_assistant":
            return await self._dev_inject_assistant(action, user_id)
        return {"ok": False, "error": f"unknown action kind: {kind}"}

    async def _dev_inject_assistant(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Inject a fake assistant message directly into working memory.

        Used for SDUI widget rendering smoke tests when no LLM provider is
        available. The action body must contain ``content`` (str) and may
        optionally specify ``session_id``.
        """
        if self._working_memory is None:
            return {"ok": False, "error": "working_memory not configured"}
        content = action.get("content")
        if not isinstance(content, str) or not content:
            return {"ok": False, "error": "content must be a non-empty string"}
        session_id = action.get("session_id") or f"sdui:{user_id}"

        try:
            from breadmind.llm.base import LLMMessage
            self._working_memory.get_or_create_session(
                session_id, user=user_id, channel=session_id
            )
            self._working_memory.add_message(
                session_id,
                LLMMessage(role="assistant", content=content),
            )
        except Exception as exc:
            logger.warning("dev_inject_assistant failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "refresh_view": "chat_view"}

    async def _chat_input(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        values = action.get("values") or {}
        text = (values.get("text") or "").strip()
        session_id = action.get("session_id") or f"sdui:{user_id}"

        if not text:
            return {"ok": True, "refresh_view": "chat_view", "noop": True}

        if self._message_handler is None:
            # Graceful degradation: keep the Phase 1 behaviour for tests
            # and environments that have no CoreAgent wired up.
            return {"ok": True, "deferred": "chat_handler"}

        try:
            await self._message_handler(text, user=user_id, channel=session_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("chat_input message_handler failed: %s", exc)
            return {"ok": False, "error": str(exc), "refresh_view": "chat_view"}

        return {"ok": True, "refresh_view": "chat_view"}

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
