import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore
from breadmind.core.tool_gap import ToolGapDetector


class TestSelfExpansionIntegration:
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
