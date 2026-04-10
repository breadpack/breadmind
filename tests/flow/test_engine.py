import asyncio
from uuid import uuid4

from breadmind.flow.dag import DAG, Step
from breadmind.flow.engine import FlowEngine, StepDispatcher
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.flow.store import FlowEventStore


class FakeDispatcher(StepDispatcher):
    def __init__(self):
        self.calls: list[tuple] = []

    async def dispatch(self, flow_id, step_id, tool, args):
        self.calls.append((flow_id, step_id, tool, args))


async def test_engine_queues_initial_ready_steps(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = FakeDispatcher()
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    await engine.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        dag = DAG(steps=[
            Step(id="a", title="A", tool="noop", args={}, depends_on=[]),
            Step(id="b", title="B", tool="noop", args={}, depends_on=["a"]),
        ])
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        ))
        await asyncio.sleep(0.2)
        dispatched_ids = [c[1] for c in dispatcher.calls]
        assert "a" in dispatched_ids
        assert "b" not in dispatched_ids  # b depends on a
    finally:
        await engine.stop()
        await bus.stop()


async def test_engine_progresses_on_step_completed(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = FakeDispatcher()
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    await engine.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        dag = DAG(steps=[
            Step(id="a", title="A", tool="noop", args={}, depends_on=[]),
            Step(id="b", title="B", tool="noop", args={}, depends_on=["a"]),
        ])
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        ))
        await asyncio.sleep(0.1)

        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_STARTED,
            payload={"step_id": "a", "started_at": "2026-04-10T00:00:00Z"},
            actor=FlowActor.WORKER,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_COMPLETED,
            payload={"step_id": "a", "result": {"ok": True}, "duration_ms": 100},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.2)

        dispatched_ids = [c[1] for c in dispatcher.calls]
        assert "a" in dispatched_ids
        assert "b" in dispatched_ids
    finally:
        await engine.stop()
        await bus.stop()


async def test_engine_completes_flow_when_all_done(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = FakeDispatcher()
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    await engine.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        dag = DAG(steps=[Step(id="a", title="A", tool="noop", args={}, depends_on=[])])
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        ))
        await asyncio.sleep(0.1)
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_COMPLETED,
            payload={"step_id": "a", "result": {}, "duration_ms": 50},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.2)

        async with test_db.acquire() as conn:
            row = await conn.fetchrow("SELECT status FROM flows WHERE id = $1", flow_id)
        assert row["status"] == "completed"
    finally:
        await engine.stop()
        await bus.stop()


async def test_engine_does_not_finalize_on_step_failed_alone(test_db):
    """STEP_FAILED without escalation should not finalize the flow; the
    engine defers finalization to the recovery controller via
    ESCALATION_RAISED."""
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = FakeDispatcher()
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    await engine.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        dag = DAG(steps=[Step(id="a", title="A", tool="noop", args={}, depends_on=[])])
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        ))
        await asyncio.sleep(0.1)
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_FAILED,
            payload={"step_id": "a", "error": "ConnectionError", "attempt": 1},
            actor=FlowActor.WORKER,
        ))
        await asyncio.sleep(0.2)

        async with test_db.acquire() as conn:
            row = await conn.fetchrow("SELECT status FROM flows WHERE id = $1", flow_id)
        # Flow should be in a non-terminal state (neither completed nor failed).
        assert row["status"] not in ("completed", "failed", "escalated")

        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "flow_failed" not in types
    finally:
        await engine.stop()
        await bus.stop()


async def test_engine_finalizes_on_escalation_raised(test_db):
    """ESCALATION_RAISED should trigger FLOW_FAILED publication."""
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    dispatcher = FakeDispatcher()
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    await engine.start()
    try:
        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        dag = DAG(steps=[Step(id="a", title="A", tool="noop", args={}, depends_on=[])])
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        ))
        await asyncio.sleep(0.1)
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.ESCALATION_RAISED,
            payload={"step_id": "a", "reason": "max attempts exceeded", "error": "boom"},
            actor=FlowActor.RECOVERY,
        ))
        await asyncio.sleep(0.2)

        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "flow_failed" in types
    finally:
        await engine.stop()
        await bus.stop()
