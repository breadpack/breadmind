import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import AgentContext, AgentResponse
from breadmind.plugins.v2_builtin.agent_loop.spawner import Spawner, SwarmPlan, SwarmTask, SpawnResult


def _make_agent(response_text="Done"):
    agent = MagicMock()
    agent.agent_id = "child_1"
    agent.handle_message = AsyncMock(return_value=AgentResponse(content=response_text))
    return agent


@pytest.fixture
def ctx():
    return AgentContext(user="test", channel="cli", session_id="s1", depth=0)


@pytest.mark.asyncio
async def test_spawn_basic(ctx):
    child = _make_agent("Task completed")
    spawner = Spawner(agent_factory=lambda tools=None: child)
    result = await spawner.spawn("Do something", ctx)
    assert result.success is True
    assert result.response == "Task completed"
    assert result.agent_id == "child_1"


@pytest.mark.asyncio
async def test_spawn_depth_limit(ctx):
    ctx.depth = 5
    spawner = Spawner(max_depth=5)
    result = await spawner.spawn("Deep task", ctx)
    assert result.success is False
    assert "depth" in result.response.lower()


@pytest.mark.asyncio
async def test_spawn_no_factory(ctx):
    spawner = Spawner(agent_factory=None)
    result = await spawner.spawn("No factory", ctx)
    assert result.success is False


@pytest.mark.asyncio
async def test_swarm_linear(ctx):
    call_order = []

    def factory(tools=None):
        agent = MagicMock()
        agent.agent_id = f"agent_{len(call_order)}"
        async def handle(msg, c):
            call_order.append(msg[:20])
            return AgentResponse(content=f"Done: {msg[:20]}")
        agent.handle_message = handle
        return agent

    spawner = Spawner(agent_factory=factory)
    plan = SwarmPlan(goal="Linear test", tasks=[
        SwarmTask(id="t1", description="First task"),
        SwarmTask(id="t2", description="Second task", depends_on=["t1"]),
    ])
    results = await spawner.execute_swarm(plan, ctx)
    assert results["t1"].success is True
    assert results["t2"].success is True
    assert len(call_order) == 2


@pytest.mark.asyncio
async def test_swarm_parallel(ctx):
    spawner = Spawner(agent_factory=lambda tools=None: _make_agent("OK"))
    plan = SwarmPlan(goal="Parallel test", tasks=[
        SwarmTask(id="t1", description="Task A"),
        SwarmTask(id="t2", description="Task B"),
        SwarmTask(id="t3", description="Task C", depends_on=["t1", "t2"]),
    ])
    results = await spawner.execute_swarm(plan, ctx)
    assert all(r.success for r in results.values())
    assert len(results) == 3
