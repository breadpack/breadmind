from uuid import UUID

from breadmind.flow.dag import DAG, Step
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.tools.delegate_work import delegate_work_impl


class FakeDAGGenerator:
    async def generate(self, *, title, description, available_tools):
        return DAG(
            steps=[
                Step(id="s1", title="Only", tool="shell_exec", args={}, depends_on=[]),
            ]
        )


async def test_delegate_work_creates_flow_and_dag(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        result = await delegate_work_impl(
            title="My task",
            description="Do things",
            user_id="alice",
            bus=bus,
            dag_generator=FakeDAGGenerator(),
            available_tools=["shell_exec"],
        )
        assert "flow_id" in result
        assert "initial_dag_summary" in result
        assert result["initial_dag_summary"]["step_count"] == 1
        assert result["initial_dag_summary"]["titles"] == ["Only"]
        flow_id = UUID(result["flow_id"])

        async with test_db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT title, user_id, status FROM flows WHERE id = $1",
                flow_id,
            )
        assert row is not None
        assert row["title"] == "My task"
        assert row["user_id"] == "alice"

        async with test_db.acquire() as conn:
            steps = await conn.fetch(
                "SELECT step_id FROM flow_steps WHERE flow_id = $1",
                flow_id,
            )
        assert len(steps) == 1
    finally:
        await bus.stop()
