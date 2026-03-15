import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.swarm import (
    SwarmManager, SwarmCoordinator, SwarmTask, SwarmResult,
    SwarmContext, SwarmMember, DEFAULT_ROLES,
)


class TestSwarmTask:
    def test_defaults(self):
        t = SwarmTask(id="t1", description="test", role="general")
        assert t.status == "pending"
        assert t.depends_on == []
        assert t.result == ""

    def test_with_dependencies(self):
        t = SwarmTask(id="t3", description="analyze", role="general", depends_on=["t1", "t2"])
        assert len(t.depends_on) == 2


class TestSwarmContext:
    def test_defaults(self):
        ctx = SwarmContext()
        assert ctx.task_graph == {}
        assert ctx.findings == []
        assert ctx.final_result == ""


class TestSwarmCoordinator:
    def test_parse_tasks_valid(self):
        coord = SwarmCoordinator()
        response = (
            "TASK|k8s_expert|Check pod health|none\n"
            "TASK|proxmox_expert|Check VM status|none\n"
            "TASK|performance_analyst|Compare results|1,2\n"
        )
        tasks = coord._parse_tasks(response)
        assert len(tasks) == 3
        assert tasks[0].role == "k8s_expert"
        assert tasks[2].depends_on == ["t1", "t2"]

    def test_parse_tasks_invalid_role(self):
        coord = SwarmCoordinator()
        response = "TASK|unknown_role|Do something|none\n"
        tasks = coord._parse_tasks(response)
        assert tasks[0].role == "general"  # Falls back to general

    def test_parse_tasks_empty(self):
        coord = SwarmCoordinator()
        tasks = coord._parse_tasks("no valid tasks here")
        assert len(tasks) == 1  # Fallback task
        assert tasks[0].role == "general"

    @pytest.mark.asyncio
    async def test_decompose_no_handler(self):
        coord = SwarmCoordinator()
        tasks = await coord.decompose("Test goal")
        assert len(tasks) == 1
        assert tasks[0].role == "general"

    @pytest.mark.asyncio
    async def test_decompose_with_handler(self):
        handler = AsyncMock(return_value="TASK|k8s_expert|Check pods|none\nTASK|general|Summarize|1")
        coord = SwarmCoordinator(message_handler=handler)
        tasks = await coord.decompose("Check cluster health")
        assert len(tasks) == 2
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_no_handler(self):
        coord = SwarmCoordinator()
        result = await coord.aggregate("goal", {"t1": "result1", "t2": "result2"})
        assert "result1" in result
        assert "result2" in result

    @pytest.mark.asyncio
    async def test_aggregate_with_handler(self):
        handler = AsyncMock(return_value="Aggregated analysis")
        coord = SwarmCoordinator(message_handler=handler)
        result = await coord.aggregate("goal", {"t1": "r1"})
        assert result == "Aggregated analysis"


class TestSwarmManager:
    def test_init(self):
        mgr = SwarmManager()
        assert len(mgr._roles) == len(DEFAULT_ROLES)
        assert mgr._swarms == {}

    def test_init_custom_roles(self):
        custom = {"my_expert": SwarmMember(role="my_expert", system_prompt="Custom expert")}
        mgr = SwarmManager(custom_roles=custom)
        assert "my_expert" in mgr._roles

    def test_get_available_roles(self):
        mgr = SwarmManager()
        roles = mgr.get_available_roles()
        assert len(roles) == len(DEFAULT_ROLES)
        assert all("role" in r and "description" in r for r in roles)

    def test_get_status_empty(self):
        mgr = SwarmManager()
        status = mgr.get_status()
        assert status["total"] == 0

    def test_get_swarm_not_found(self):
        mgr = SwarmManager()
        assert mgr.get_swarm("nonexistent") is None

    def test_list_swarms_empty(self):
        mgr = SwarmManager()
        assert mgr.list_swarms() == []

    @pytest.mark.asyncio
    async def test_spawn_swarm(self):
        handler = AsyncMock(return_value="TASK|general|Do the thing|none")
        mgr = SwarmManager(message_handler=handler)
        result = await mgr.spawn_swarm("Test goal")
        assert result.id
        assert result.goal == "Test goal"
        assert result.status in ("pending", "running")

    def test_set_message_handler(self):
        mgr = SwarmManager()
        handler = AsyncMock()
        mgr.set_message_handler(handler)
        assert mgr._message_handler == handler
        assert mgr._coordinator._message_handler == handler


class TestDefaultRoles:
    def test_all_roles_have_required_fields(self):
        for name, member in DEFAULT_ROLES.items():
            assert member.role == name
            assert member.system_prompt
            assert member.description
