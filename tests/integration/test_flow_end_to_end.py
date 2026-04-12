import asyncio
from uuid import UUID


from breadmind.flow.events import FlowEvent, EventType, FlowActor
from breadmind.flow.store import FlowEventStore
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.engine import FlowEngine
from breadmind.flow.recovery import RecoveryController, RetryPolicy
from breadmind.flow.dag import DAG, Step
from breadmind.tools.delegate_work import delegate_work_impl


class FakeDAGGen:
    async def generate(self, *, title, description, available_tools):
        return DAG(steps=[
            Step(id="a", title="First", tool="noop", args={}, depends_on=[]),
            Step(id="b", title="Second", tool="noop", args={}, depends_on=["a"]),
        ])


class AutoCompleteDispatcher:
    """Simulates a worker by immediately emitting STEP_STARTED and STEP_COMPLETED
    when the engine dispatches a step."""

    def __init__(self, bus):
        self.bus = bus
        self.calls = []

    async def dispatch(self, flow_id, step_id, tool, args):
        self.calls.append((flow_id, step_id))
        # Yield to let other tasks (engine subscription loop) progress first.
        await asyncio.sleep(0)
        await self.bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_STARTED,
            payload={"step_id": step_id, "started_at": "2026-04-10T00:00:00Z"},
            actor=FlowActor.WORKER,
        ))
        await self.bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_COMPLETED,
            payload={"step_id": step_id, "result": {"ok": True}, "duration_ms": 10},
            actor=FlowActor.WORKER,
        ))


async def test_end_to_end_simple_flow(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()

    dispatcher = AutoCompleteDispatcher(bus)
    engine = FlowEngine(bus=bus, dispatcher=dispatcher)
    recovery = RecoveryController(
        bus=bus,
        dispatcher=dispatcher,
        policy=RetryPolicy(max_attempts=2, initial_delay=0.01, backoff_factor=1.0),
    )
    await engine.start()
    await recovery.start()

    try:
        result = await delegate_work_impl(
            title="Do the thing",
            description="End-to-end test",
            user_id="alice",
            bus=bus,
            dag_generator=FakeDAGGen(),
            available_tools=["noop"],
        )
        assert "flow_id" in result
        flow_id = UUID(result["flow_id"])

        # Wait up to ~5s for completion
        completed = False
        for _ in range(200):
            async with test_db.acquire() as conn:
                row = await conn.fetchrow("SELECT status FROM flows WHERE id = $1", flow_id)
            if row and row["status"] == "completed":
                completed = True
                break
            await asyncio.sleep(0.025)
        assert completed, "flow did not reach completed status in time"

        # Both steps should be recorded as completed
        async with test_db.acquire() as conn:
            steps = await conn.fetch(
                "SELECT step_id, status FROM flow_steps WHERE flow_id = $1 ORDER BY step_id",
                flow_id,
            )
        assert [(s["step_id"], s["status"]) for s in steps] == [("a", "completed"), ("b", "completed")]

        # Verify event trail includes key events
        events = await bus.replay(flow_id)
        types = [e.event_type.value for e in events]
        assert "flow_created" in types
        assert "dag_proposed" in types
        assert "step_started" in types
        assert "step_completed" in types
        assert "flow_completed" in types
    finally:
        await recovery.stop()
        await engine.stop()
        await bus.stop()
