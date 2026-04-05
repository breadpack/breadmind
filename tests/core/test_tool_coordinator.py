"""Tests for ToolCoordinator extracted from CoreAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from breadmind.core.tool_coordinator import ToolCoordinator


def _make_tool(name: str, description: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description)


def _make_coordinator(**kwargs) -> ToolCoordinator:
    registry = kwargs.pop("tool_registry", MagicMock())
    guard = kwargs.pop("safety_guard", MagicMock())
    return ToolCoordinator(tool_registry=registry, safety_guard=guard, **kwargs)


# --- filter_relevant_tools tests ---


class TestFilterRelevantTools:
    def test_returns_all_when_under_max(self):
        coord = _make_coordinator()
        tools = [_make_tool(f"tool_{i}") for i in range(5)]
        result = coord.filter_relevant_tools(tools, "hello", max_tools=10)
        assert result == tools

    def test_always_include_tools_preserved(self):
        coord = _make_coordinator()
        always = [_make_tool(name) for name in ["shell_exec", "web_search", "file_read"]]
        others = [_make_tool(f"obscure_{i}", "unrelated stuff") for i in range(40)]
        all_tools = always + others
        result = coord.filter_relevant_tools(all_tools, "hello", max_tools=10)
        result_names = {t.name for t in result}
        assert {"shell_exec", "web_search", "file_read"}.issubset(result_names)
        assert len(result) <= 10

    def test_intent_hints_included(self):
        coord = _make_coordinator()
        intent = SimpleNamespace(tool_hints={"my_special_tool"}, keywords=[])
        tools = [_make_tool("my_special_tool")] + [
            _make_tool(f"other_{i}", "unrelated") for i in range(40)
        ]
        result = coord.filter_relevant_tools(tools, "do something", max_tools=5, intent=intent)
        result_names = {t.name for t in result}
        assert "my_special_tool" in result_names

    def test_keyword_scoring(self):
        coord = _make_coordinator()
        tools = [
            _make_tool("kubernetes_deploy", "deploy containers to kubernetes"),
            _make_tool("file_compress", "compress files into archive"),
        ] + [_make_tool(f"filler_{i}") for i in range(40)]
        result = coord.filter_relevant_tools(tools, "deploy kubernetes", max_tools=5)
        result_names = [t.name for t in result]
        # kubernetes_deploy should score higher and be included
        assert "kubernetes_deploy" in result_names


# --- get_pending_approvals tests ---


class TestPendingApprovals:
    def test_empty_initially(self):
        coord = _make_coordinator()
        assert coord.get_pending_approvals() == []

    def test_returns_pending_only(self):
        coord = _make_coordinator()
        coord._pending_approvals["a1"] = {"status": "pending", "tool": "t1", "args": {}}
        coord._pending_approvals["a2"] = {"status": "approved", "tool": "t2", "args": {}}
        coord._pending_approvals["a3"] = {"status": "pending", "tool": "t3", "args": {}}
        result = coord.get_pending_approvals()
        assert len(result) == 2
        ids = {r["approval_id"] for r in result}
        assert ids == {"a1", "a3"}


# --- approve_tool tests ---


class TestApproveTool:
    @pytest.mark.asyncio
    async def test_approve_missing_id(self):
        coord = _make_coordinator()
        result = await coord.approve_tool("nonexistent")
        assert not result.success
        assert "No pending approval" in result.output

    @pytest.mark.asyncio
    async def test_approve_already_approved(self):
        coord = _make_coordinator()
        coord._pending_approvals["a1"] = {"status": "approved", "tool": "t", "args": {}}
        result = await coord.approve_tool("a1")
        assert not result.success

    @pytest.mark.asyncio
    async def test_approve_executes_tool(self):
        from breadmind.tools.registry import ToolResult

        registry = AsyncMock()
        registry.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
        coord = _make_coordinator(tool_registry=registry)
        coord._pending_approvals["a1"] = {
            "status": "pending", "tool": "my_tool", "args": {"x": 1},
            "user": "u", "channel": "c",
        }
        result = await coord.approve_tool("a1")
        assert result.success
        assert result.output == "done"
        registry.execute.assert_awaited_once_with("my_tool", {"x": 1})
        assert coord._pending_approvals["a1"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_approve_logs_audit(self):
        from breadmind.tools.registry import ToolResult

        registry = AsyncMock()
        registry.execute = AsyncMock(return_value=ToolResult(success=True, output="ok"))
        audit = MagicMock()
        coord = _make_coordinator(tool_registry=registry, audit_logger=audit)
        coord._pending_approvals["a1"] = {
            "status": "pending", "tool": "t", "args": {},
            "user": "u", "channel": "c",
        }
        await coord.approve_tool("a1")
        audit.log_approval_request.assert_called_once_with("u", "c", "t", "approved")
        audit.log_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_timeout(self):
        import asyncio

        async def slow_exec(*a, **kw):
            await asyncio.sleep(10)

        registry = MagicMock()
        registry.execute = slow_exec
        coord = _make_coordinator(tool_registry=registry, tool_timeout=1)
        coord._pending_approvals["a1"] = {
            "status": "pending", "tool": "t", "args": {},
            "user": "u", "channel": "c",
        }
        result = await coord.approve_tool("a1")
        assert not result.success
        assert "timed out" in result.output


# --- deny_tool tests ---


class TestDenyTool:
    def test_deny_sets_status(self):
        coord = _make_coordinator()
        coord._pending_approvals["a1"] = {
            "status": "pending", "tool": "t", "args": {},
            "user": "u", "channel": "c",
        }
        coord.deny_tool("a1")
        assert coord._pending_approvals["a1"]["status"] == "denied"

    def test_deny_nonexistent_is_noop(self):
        coord = _make_coordinator()
        coord.deny_tool("nonexistent")  # should not raise

    def test_deny_logs_audit(self):
        audit = MagicMock()
        coord = _make_coordinator(audit_logger=audit)
        coord._pending_approvals["a1"] = {
            "status": "pending", "tool": "t", "args": {},
            "user": "u", "channel": "c",
        }
        coord.deny_tool("a1")
        audit.log_approval_request.assert_called_once_with("u", "c", "t", "denied")


# --- detect_loop tests ---


class TestDetectLoop:
    def test_no_loop_with_different_calls(self):
        coord = _make_coordinator()
        recent: list[tuple[str, str]] = []
        tc1 = SimpleNamespace(name="tool_a", arguments={"x": 1})
        tc2 = SimpleNamespace(name="tool_b", arguments={"y": 2})
        tc3 = SimpleNamespace(name="tool_c", arguments={"z": 3})
        assert coord.detect_loop(recent, [tc1]) is None
        assert coord.detect_loop(recent, [tc2]) is None
        assert coord.detect_loop(recent, [tc3]) is None

    def test_loop_detected_same_calls(self):
        coord = _make_coordinator()
        recent: list[tuple[str, str]] = []
        tc = SimpleNamespace(name="tool_a", arguments={"x": 1})
        coord.detect_loop(recent, [tc])
        coord.detect_loop(recent, [tc])
        result = coord.detect_loop(recent, [tc])
        assert result is not None
        assert "tool_a" in result
        assert "3" in result

    def test_custom_threshold(self):
        coord = _make_coordinator()
        recent: list[tuple[str, str]] = []
        tc = SimpleNamespace(name="tool_a", arguments={"x": 1})
        # With threshold=2, should detect after 2 identical calls
        coord.detect_loop(recent, [tc], threshold=2)
        result = coord.detect_loop(recent, [tc], threshold=2)
        assert result is not None

    def test_no_loop_below_threshold(self):
        coord = _make_coordinator()
        recent: list[tuple[str, str]] = []
        tc = SimpleNamespace(name="tool_a", arguments={"x": 1})
        coord.detect_loop(recent, [tc])
        result = coord.detect_loop(recent, [tc])
        # Default threshold is 3, so 2 identical calls is not a loop
        assert result is None


# --- pending_approvals property ---


class TestPendingApprovalsProperty:
    def test_shared_reference(self):
        coord = _make_coordinator()
        # Property should return the same dict object
        approvals = coord.pending_approvals
        approvals["test"] = {"status": "pending"}
        assert coord._pending_approvals["test"]["status"] == "pending"
