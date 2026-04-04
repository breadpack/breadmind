"""E2E: 서브에이전트 spawn + SwarmPlan."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import AgentContext, AgentResponse
from breadmind.plugins.v2_builtin.agent_loop.spawner import Spawner, SwarmPlan, SwarmTask


def _make_child(response: str):
    agent = MagicMock()
    agent.agent_id = "child"
    agent.handle_message = AsyncMock(return_value=AgentResponse(content=response))
    return agent


@pytest.mark.asyncio
async def test_spawn_child_agent():
    """Spawn a child agent and get response."""
    spawner = Spawner(agent_factory=lambda tools=None: _make_child("Child done"))
    ctx = AgentContext(user="admin", channel="cli", session_id="s1", depth=0)
    result = await spawner.spawn("Analyze logs", ctx)
    assert result.success is True
    assert result.response == "Child done"


@pytest.mark.asyncio
async def test_spawn_respects_depth_limit():
    """Spawn at max depth returns error."""
    spawner = Spawner(max_depth=3)
    ctx = AgentContext(user="admin", channel="cli", session_id="s1", depth=3)
    result = await spawner.spawn("Too deep", ctx)
    assert result.success is False
    assert "depth" in result.response.lower()


@pytest.mark.asyncio
async def test_swarm_plan_execution():
    """Execute a SwarmPlan with dependencies."""
    order = []

    def factory(tools=None):
        agent = MagicMock()
        agent.agent_id = f"agent_{len(order)}"
        async def handle(msg, ctx):
            order.append(msg[:30])
            return AgentResponse(content=f"Done: {msg[:30]}")
        agent.handle_message = handle
        return agent

    spawner = Spawner(agent_factory=factory)
    ctx = AgentContext(user="admin", channel="cli", session_id="s1")

    plan = SwarmPlan(goal="Full infra check", tasks=[
        SwarmTask(id="scan", description="Scan infrastructure"),
        SwarmTask(id="diagnose", description="Diagnose issues", depends_on=["scan"]),
        SwarmTask(id="fix", description="Fix found issues", depends_on=["diagnose"]),
    ])

    results = await spawner.execute_swarm(plan, ctx)
    assert len(results) == 3
    assert all(r.success for r in results.values())
    # Verify order: scan must appear before diagnose (which prefixes prior results)
    scan_idx = next(i for i, msg in enumerate(order) if "Scan infrastructure" in msg)
    diagnose_idx = next(i for i, msg in enumerate(order) if "Diagnose issues" in msg or "[Result from scan]" in msg)
    assert scan_idx < diagnose_idx


@pytest.mark.asyncio
async def test_swarm_parallel_tasks():
    """Tasks without dependencies run in parallel."""
    spawner = Spawner(agent_factory=lambda tools=None: _make_child("OK"))
    ctx = AgentContext(user="admin", channel="cli", session_id="s1")

    plan = SwarmPlan(goal="Parallel check", tasks=[
        SwarmTask(id="k8s", description="Check K8s"),
        SwarmTask(id="proxmox", description="Check Proxmox"),
        SwarmTask(id="summary", description="Summarize", depends_on=["k8s", "proxmox"]),
    ])

    results = await spawner.execute_swarm(plan, ctx)
    assert len(results) == 3
    assert results["summary"].success is True
