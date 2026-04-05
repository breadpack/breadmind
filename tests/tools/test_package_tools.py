"""Tests for package_tools — agent-facing tool wrappers."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.tools.package_manager import (
    Package,
    PackageAction,
    PackageActionResult,
    PackageManager,
    PackageType,
)
from breadmind.tools.package_tools import create_package_tools


@pytest.fixture
def mock_manager():
    return AsyncMock(spec=PackageManager)


@pytest.fixture
def tools(mock_manager):
    return create_package_tools(mock_manager)


def _get_tool(tools, name: str):
    for t in tools:
        if t.__name__ == name:
            return t
    raise KeyError(f"Tool '{name}' not found in {[t.__name__ for t in tools]}")


class TestCreatePackageTools:
    def test_returns_eight_tools(self, tools):
        assert len(tools) == 8

    def test_all_have_tool_definition(self, tools):
        for t in tools:
            assert hasattr(t, "_tool_definition"), f"{t.__name__} missing _tool_definition"

    def test_tool_names(self, tools):
        names = {t.__name__ for t in tools}
        expected = {
            "pkg_search", "pkg_install", "pkg_uninstall", "pkg_list",
            "pkg_enable", "pkg_disable", "pkg_status", "pkg_info",
        }
        assert names == expected


class TestPkgSearch:
    async def test_search_with_results(self, tools, mock_manager):
        mock_manager.search = AsyncMock(return_value=[
            Package(name="github", type=PackageType.MCP_SERVER,
                    description="GitHub MCP", status="available", source="clawhub"),
        ])
        fn = _get_tool(tools, "pkg_search")
        result = await fn(query="github", type="mcp_server")
        assert result.success is True
        assert "github" in result.output

    async def test_search_no_results(self, tools, mock_manager):
        mock_manager.search = AsyncMock(return_value=[])
        fn = _get_tool(tools, "pkg_search")
        result = await fn(query="nonexistent")
        assert result.success is True
        assert "No packages found" in result.output

    async def test_search_no_type_filter(self, tools, mock_manager):
        mock_manager.search = AsyncMock(return_value=[])
        fn = _get_tool(tools, "pkg_search")
        result = await fn(query="test", type="")
        # Should pass None as pkg_type
        mock_manager.search.assert_awaited_once_with("test", None, limit=10)


class TestPkgInstall:
    async def test_install_success(self, tools, mock_manager):
        mock_manager.install = AsyncMock(return_value=PackageActionResult(
            success=True, action=PackageAction.INSTALL,
            package_type=PackageType.SKILL, package_name="review",
            message="Skill 'review' installed.",
        ))
        fn = _get_tool(tools, "pkg_install")
        result = await fn(name="review", type="skill")
        assert result.success is True
        assert "installed" in result.output

    async def test_install_invalid_type(self, tools, mock_manager):
        fn = _get_tool(tools, "pkg_install")
        result = await fn(name="foo", type="invalid_type")
        assert result.success is False
        assert "Invalid package type" in result.output


class TestPkgUninstall:
    async def test_uninstall_success(self, tools, mock_manager):
        mock_manager.uninstall = AsyncMock(return_value=PackageActionResult(
            success=True, action=PackageAction.UNINSTALL,
            package_type=PackageType.PLUGIN, package_name="slack",
            message="Plugin 'slack' uninstalled.",
        ))
        fn = _get_tool(tools, "pkg_uninstall")
        result = await fn(name="slack", type="plugin")
        assert result.success is True

    async def test_uninstall_invalid_type(self, tools, mock_manager):
        fn = _get_tool(tools, "pkg_uninstall")
        result = await fn(name="foo", type="bad")
        assert result.success is False


class TestPkgList:
    async def test_list_all(self, tools, mock_manager):
        mock_manager.list_packages = AsyncMock(return_value=[
            Package(name="shell_exec", type=PackageType.TOOL,
                    description="Shell", status="enabled", source="builtin"),
        ])
        fn = _get_tool(tools, "pkg_list")
        result = await fn()
        assert result.success is True
        assert "shell_exec" in result.output

    async def test_list_empty(self, tools, mock_manager):
        mock_manager.list_packages = AsyncMock(return_value=[])
        fn = _get_tool(tools, "pkg_list")
        result = await fn()
        assert "No packages found" in result.output


class TestPkgEnableDisable:
    async def test_enable(self, tools, mock_manager):
        mock_manager.enable = AsyncMock(return_value=PackageActionResult(
            success=True, action=PackageAction.ENABLE,
            package_type=PackageType.PLUGIN, package_name="monitoring",
            message="Plugin 'monitoring' enabled.",
        ))
        fn = _get_tool(tools, "pkg_enable")
        result = await fn(name="monitoring", type="plugin")
        assert result.success is True

    async def test_disable(self, tools, mock_manager):
        mock_manager.disable = AsyncMock(return_value=PackageActionResult(
            success=True, action=PackageAction.DISABLE,
            package_type=PackageType.PLUGIN, package_name="monitoring",
            message="Plugin 'monitoring' disabled.",
        ))
        fn = _get_tool(tools, "pkg_disable")
        result = await fn(name="monitoring", type="plugin")
        assert result.success is True


class TestPkgStatus:
    async def test_status(self, tools, mock_manager):
        mock_manager.get_status = AsyncMock(return_value={
            "tool": {"total": 5, "enabled": 5, "disabled": 0, "installed": 0},
            "skill": {"total": 2, "enabled": 0, "disabled": 0, "installed": 2},
        })
        fn = _get_tool(tools, "pkg_status")
        result = await fn()
        assert result.success is True
        assert "tool" in result.output
        assert "skill" in result.output


class TestPkgInfo:
    async def test_info_found(self, tools, mock_manager):
        mock_manager.get_info = AsyncMock(return_value=Package(
            name="shell_exec", type=PackageType.TOOL,
            description="Execute shell commands", status="enabled", source="builtin",
        ))
        fn = _get_tool(tools, "pkg_info")
        result = await fn(name="shell_exec")
        assert result.success is True
        data = json.loads(result.output)
        assert data["name"] == "shell_exec"

    async def test_info_not_found(self, tools, mock_manager):
        mock_manager.get_info = AsyncMock(return_value=None)
        fn = _get_tool(tools, "pkg_info")
        result = await fn(name="ghost")
        assert result.success is False
        assert "not found" in result.output
