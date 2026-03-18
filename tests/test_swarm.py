import asyncio
import pytest
from unittest.mock import AsyncMock
from breadmind.core.swarm import (
    SwarmManager, SwarmTask, SwarmContext, SwarmMember, DEFAULT_ROLES,
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


class TestSwarmMemberSource:
    def test_default_source_is_manual(self):
        member = SwarmMember(role="test", system_prompt="prompt")
        assert member.source == "manual"

    def test_auto_source(self):
        member = SwarmMember(role="test", system_prompt="prompt", source="auto")
        assert member.source == "auto"


class TestSwarmManagerAddRoleSource:
    def test_add_role_with_source(self):
        manager = SwarmManager()
        manager.add_role("new_role", "prompt", "desc", source="auto")
        roles = manager.export_roles()
        assert roles["new_role"]["source"] == "auto"

    def test_import_roles_default_source(self):
        manager = SwarmManager()
        manager.import_roles({"old_role": {"system_prompt": "p", "description": "d"}})
        member = manager._roles.get("old_role")
        assert member is not None
        assert member.source == "manual"


class TestSwarmManagerIntegration:
    @pytest.mark.asyncio
    async def test_swarm_records_performance(self):
        from breadmind.core.performance import PerformanceTracker
        tracker = PerformanceTracker()
        async def mock_handler(msg, user="", channel=""):
            if "decompose" in channel or "Decompose" in msg:
                return "TASK|general|Do something|none"
            if "aggregate" in channel or "aggregating" in msg.lower():
                return "Summary: all good"
            return "Task completed successfully"
        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        swarm = await manager.spawn_swarm("Test goal")
        for _ in range(50):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break
        stats = tracker.get_role_stats("general")
        assert stats is not None
        assert stats.total_runs >= 1

    @pytest.mark.asyncio
    async def test_swarm_uses_team_builder(self):
        from breadmind.core.performance import PerformanceTracker
        from breadmind.core.skill_store import SkillStore
        from breadmind.core.team_builder import TeamBuilder
        tracker = PerformanceTracker()
        skill_store = SkillStore()
        team_builder_called = False
        async def mock_handler(msg, user="", channel=""):
            nonlocal team_builder_called
            if "team_build" in channel:
                team_builder_called = True
                return "ASSESS|general|0.8|use\nCREATE_NONE"
            if "decompose" in channel:
                return "TASK|general|Do task|none"
            if "aggregate" in channel:
                return "Done"
            return "OK"
        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        team_builder = TeamBuilder(manager, tracker, skill_store, mock_handler)
        manager.set_team_builder(team_builder)
        swarm = await manager.spawn_swarm("Test")
        for _ in range(50):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break
        assert team_builder_called
