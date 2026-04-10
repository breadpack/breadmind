"""Tests for :mod:`breadmind.sdui.actions`."""
from __future__ import annotations

from uuid import uuid4

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler


async def test_intervention_action_emits_event(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        handler = ActionHandler(bus=bus)

        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "alice", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))

        result = await handler.handle({
            "kind": "intervention",
            "flow_id": str(flow_id),
            "step_id": "s1",
            "value": "approve",
        }, user_id="alice")

        assert result["ok"] is True
        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "user_intervention" in types
    finally:
        await bus.stop()


async def test_chat_input_action_returns_deferred(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        handler = ActionHandler(bus=bus)
        result = await handler.handle({
            "kind": "chat_input",
            "session_id": "",
            "values": {"text": "hello"},
        }, user_id="alice")
        assert result["ok"] is True
        assert result.get("deferred") == "chat_handler"
    finally:
        await bus.stop()


async def test_unknown_action_returns_error(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        handler = ActionHandler(bus=bus)
        result = await handler.handle({"kind": "bogus"}, user_id="alice")
        assert result["ok"] is False
        assert "unknown" in result.get("error", "").lower()
    finally:
        await bus.stop()
