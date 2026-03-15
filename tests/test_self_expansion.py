import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore
from breadmind.core.tool_gap import ToolGapDetector
from breadmind.core.team_builder import TeamBuilder
from breadmind.core.swarm import SwarmManager


class TestSelfExpansionIntegration:
    @pytest.mark.asyncio
    async def test_full_expansion_flow(self):
        """Test: TeamBuilder creates role -> Swarm executes -> PerformanceTracker records."""
        tracker = PerformanceTracker()
        skill_store = SkillStore(tracker=tracker)

        call_log = []
        async def mock_handler(msg, user="", channel=""):
            call_log.append(channel)
            if "team_build" in channel:
                return "ASSESS|general|0.3|skip\nCREATE|test_expert|Test expert|You are a test expert.|test"
            if "decompose" in channel:
                return "TASK|test_expert|Run the test analysis|none"
            if "aggregate" in channel:
                return "Test analysis complete"
            return "Task done"

        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        team_builder = TeamBuilder(manager, tracker, skill_store, mock_handler)
        manager.set_team_builder(team_builder)

        swarm = await manager.spawn_swarm("Analyze test coverage")
        for _ in range(100):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break

        # Verify: role was created
        roles = [r["role"] for r in manager.get_available_roles()]
        assert "test_expert" in roles

        # Verify: performance was tracked
        stats = tracker.get_role_stats("test_expert")
        assert stats is not None
        assert stats.total_runs >= 1

    @pytest.mark.asyncio
    async def test_tool_gap_to_suggestion_flow(self):
        """Test: unknown tool -> ToolGapDetector suggests MCP -> suggestion available."""
        registry = MagicMock()
        registry.get_tool.return_value = None
        mcp_manager = AsyncMock()
        search_engine = AsyncMock()

        mock_result = MagicMock()
        mock_result.name = "grafana-mcp"
        mock_result.description = "Grafana dashboard tools"
        mock_result.install_command = "npx grafana-mcp"
        mock_result.source = "clawhub"
        search_engine.search = AsyncMock(return_value=[mock_result])

        detector = ToolGapDetector(registry, mcp_manager, search_engine)
        result = await detector.check_and_resolve("grafana_query", {}, "user", "ch")

        assert not result.resolved
        assert len(result.suggestions) == 1
        assert result.suggestions[0].mcp_name == "grafana-mcp"

        # Verify pending install exists
        pending = detector.get_pending_installs()
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self):
        """Test: all components survive export/import cycle."""
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "task1", True, 100.0, "ok")
        exported_tracker = tracker.export_stats()

        skill_store = SkillStore()
        await skill_store.add_skill("s1", "desc", "prompt", ["step"], ["kw"], "auto")
        exported_skills = skill_store.export_skills()

        # Import into fresh instances
        tracker2 = PerformanceTracker()
        tracker2.import_stats(exported_tracker)
        assert tracker2.get_role_stats("role_a").total_runs == 1

        skill_store2 = SkillStore()
        skill_store2.import_skills(exported_skills)
        skill = await skill_store2.get_skill("s1")
        assert skill is not None
        assert skill.source == "auto"
