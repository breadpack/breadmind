import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.tool_gap import ToolGapDetector, ToolGapResult, MCPSuggestion


class TestToolGapResult:
    def test_unresolved_result(self):
        result = ToolGapResult(resolved=False, message="Not found", suggestions=[])
        assert result.resolved is False
        assert result.suggestions == []


class TestMCPSuggestion:
    def test_create_suggestion(self):
        s = MCPSuggestion(id="abc123", tool_name="kubectl_exec", mcp_name="kubernetes-mcp",
            mcp_description="K8s management tools", install_command="npx kubernetes-mcp", source="clawhub")
        assert s.status == "pending"


class TestToolGapDetector:
    def _make_detector(self, search_results=None):
        registry = MagicMock()
        registry.get_tool.return_value = None
        mcp_manager = AsyncMock()
        search_engine = AsyncMock()
        if search_results is not None:
            search_engine.search = AsyncMock(return_value=search_results)
        else:
            search_engine.search = AsyncMock(return_value=[])
        return ToolGapDetector(tool_registry=registry, mcp_manager=mcp_manager, search_engine=search_engine)

    @pytest.mark.asyncio
    async def test_check_no_suggestions(self):
        detector = self._make_detector(search_results=[])
        result = await detector.check_and_resolve("unknown_tool", {}, "user1", "ch1")
        assert result.resolved is False
        assert len(result.suggestions) == 0

    @pytest.mark.asyncio
    async def test_check_with_suggestions(self):
        mock_result = MagicMock()
        mock_result.name = "k8s-mcp"
        mock_result.description = "Kubernetes tools"
        mock_result.install_command = "npx k8s-mcp"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        result = await detector.check_and_resolve("kubectl_exec", {}, "user1", "ch1")
        assert result.resolved is False
        assert len(result.suggestions) == 1
        assert result.suggestions[0].mcp_name == "k8s-mcp"

    @pytest.mark.asyncio
    async def test_cache_prevents_duplicate_searches(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-a"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_x", {}, "u", "c")
        await detector.check_and_resolve("tool_x", {}, "u", "c")
        assert detector._search_engine.search.call_count == 1

    @pytest.mark.asyncio
    async def test_pending_installs(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-b"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_y", {}, "u", "c")
        pending = detector.get_pending_installs()
        assert len(pending) == 1
        assert pending[0]["mcp_name"] == "mcp-b"

    @pytest.mark.asyncio
    async def test_deny_install(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-c"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_z", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]
        await detector.deny_install(sid)
        assert len(detector.get_pending_installs()) == 0

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        detector = self._make_detector()
        detector._search_engine.search = AsyncMock(side_effect=Exception("Network error"))
        result = await detector.check_and_resolve("tool_err", {}, "u", "c")
        assert result.resolved is False
        assert "failed" in result.message.lower() or len(result.suggestions) == 0

    @pytest.mark.asyncio
    async def test_approve_install(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-d"
        mock_result.description = "desc"
        mock_result.install_command = "npx mcp-d"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_d", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]
        detector._mcp_manager.start_stdio_server = AsyncMock(return_value=[MagicMock(name="tool_d_v1")])
        result = await detector.approve_install(sid)
        assert "Installed" in result
        assert "mcp-d" in result

    @pytest.mark.asyncio
    async def test_approve_install_failure(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-e"
        mock_result.description = "desc"
        mock_result.install_command = "npx mcp-e"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_e", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]
        detector._mcp_manager.start_stdio_server = AsyncMock(side_effect=Exception("Server crash"))
        result = await detector.approve_install(sid)
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_search_for_capability(self):
        mock_result = MagicMock()
        mock_result.name = "monitoring-mcp"
        mock_result.description = "Monitoring tools"
        mock_result.install_command = "npx monitoring-mcp"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        detector._search_engine.search = AsyncMock(return_value=[mock_result])
        suggestions = await detector.search_for_capability("monitoring dashboards")
        assert len(suggestions) == 1
        assert suggestions[0].mcp_name == "monitoring-mcp"

    @pytest.mark.asyncio
    async def test_max_pending_eviction(self):
        mock_result = MagicMock()
        mock_result.name = "mcp"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"
        detector = self._make_detector(search_results=[mock_result])
        for i in range(12):
            detector._search_cache.clear()
            await detector.check_and_resolve(f"tool_{i}", {}, "u", "c")
        assert len(detector.get_pending_installs()) <= 10
