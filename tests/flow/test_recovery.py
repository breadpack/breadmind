import asyncio
from uuid import uuid4

from breadmind.flow.engine import StepDispatcher
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.flow.recovery import RecoveryController, RetryPolicy
from breadmind.flow.store import FlowEventStore


class RecordDispatcher(StepDispatcher):
    def __init__(self):
        self.calls = []

    async def dispatch(self, flow_id, step_id, tool, args):
        self.calls.append((flow_id, step_id))


async def test_recovery_retries_on_transient_failure(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = RecordDispatcher()
    policy = RetryPolicy(max_attempts=3, initial_delay=0.01, backoff_factor=1.0)
    recovery = RecoveryController(bus=bus, dispatcher=dispatcher, policy=policy)
    await recovery.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": [{"id": "s1", "title": "S1", "tool": "t", "args": {}, "depends_on": []}]},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_FAILED,
            payload={"step_id": "s1", "error": "ConnectionError: transient", "attempt": 1},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.2)
        assert any(call[1] == "s1" for call in dispatcher.calls)
    finally:
        await recovery.stop()
        await bus.stop()


async def test_recovery_escalates_after_max_attempts(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = RecordDispatcher()
    policy = RetryPolicy(max_attempts=2, initial_delay=0.01, backoff_factor=1.0)
    recovery = RecoveryController(bus=bus, dispatcher=dispatcher, policy=policy)
    await recovery.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": [{"id": "s1", "title": "S1", "tool": "t", "args": {}, "depends_on": []}]},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_FAILED,
            payload={"step_id": "s1", "error": "ConnectionError", "attempt": 2},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.3)

        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "escalation_raised" in types
    finally:
        await recovery.stop()
        await bus.stop()


async def test_recovery_escalates_non_transient(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = RecordDispatcher()
    policy = RetryPolicy(max_attempts=3, initial_delay=0.01, backoff_factor=1.0)
    recovery = RecoveryController(bus=bus, dispatcher=dispatcher, policy=policy)
    await recovery.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": [{"id": "s1", "title": "S1", "tool": "t", "args": {}, "depends_on": []}]},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_FAILED,
            payload={"step_id": "s1", "error": "ValueError: bad input", "attempt": 1},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.2)

        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "escalation_raised" in types
        # Should NOT have retried on a non-transient error.
        assert len(dispatcher.calls) == 0
    finally:
        await recovery.stop()
        await bus.stop()
