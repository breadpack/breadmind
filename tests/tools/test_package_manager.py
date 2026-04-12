"""Tests for the unified PackageManager and IntentParser."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.tools.package_manager import (
    IntentParser,
    Package,
    PackageAction,
    PackageActionResult,
    PackageManager,
    PackageType,
)


# ---------------------------------------------------------------------------
# IntentParser tests
# ---------------------------------------------------------------------------

class TestIntentParser:
    def setup_method(self):
        self.parser = IntentParser()

    # --- Action detection ---

    def test_detect_install_action(self):
        action, _, _ = self.parser.parse("Install the GitHub MCP server")
        assert action == PackageAction.INSTALL

    def test_detect_uninstall_action(self):
        action, _, _ = self.parser.parse("Remove the slack plugin")
        assert action == PackageAction.UNINSTALL

    def test_detect_search_action(self):
        action, _, _ = self.parser.parse("Search for kubernetes tools")
        assert action == PackageAction.SEARCH

    def test_detect_list_action(self):
        action, _, _ = self.parser.parse("Show me all plugins")
        assert action == PackageAction.LIST

    def test_detect_enable_action(self):
        action, _, _ = self.parser.parse("Enable the monitoring plugin")
        assert action == PackageAction.ENABLE

    def test_detect_disable_action(self):
        action, _, _ = self.parser.parse("Disable shell_exec")
        assert action == PackageAction.DISABLE

    def test_detect_status_action(self):
        action, _, _ = self.parser.parse("What MCP servers are running?")
        assert action == PackageAction.STATUS

    def test_detect_info_action(self):
        action, _, _ = self.parser.parse("Info about the git tool")
        assert action == PackageAction.INFO

    def test_detect_update_action(self):
        action, _, _ = self.parser.parse("Update all skills")
        assert action == PackageAction.UPDATE

    # --- Type detection ---

    def test_detect_mcp_type(self):
        _, pkg_type, _ = self.parser.parse("Install the GitHub MCP server")
        assert pkg_type == PackageType.MCP_SERVER

    def test_detect_plugin_type(self):
        _, pkg_type, _ = self.parser.parse("Remove the slack plugin")
        assert pkg_type == PackageType.PLUGIN

    def test_detect_tool_type(self):
        _, pkg_type, _ = self.parser.parse("Search for kubernetes tools")
        assert pkg_type == PackageType.TOOL

    def test_detect_skill_type(self):
        _, pkg_type, _ = self.parser.parse("Add a code review skill")
        assert pkg_type == PackageType.SKILL

    def test_detect_search_provider_type(self):
        _, pkg_type, _ = self.parser.parse("List search providers")
        assert pkg_type == PackageType.SEARCH_PROVIDER

    def test_no_type_detected(self):
        _, pkg_type, _ = self.parser.parse("Install foobar")
        assert pkg_type is None

    # --- Query extraction ---

    def test_extract_query_simple(self):
        _, _, query = self.parser.parse("Search for kubernetes tools")
        assert "kubernetes" in query

    def test_extract_query_removes_fillers(self):
        _, _, query = self.parser.parse("Show me all the installed plugins")
        # Filler words like "me", "all", "the" should be removed
        assert "me" not in query.split()
        assert "the" not in query.split()

    # --- Korean intent parsing ---

    def test_korean_install(self):
        action, _, _ = self.parser.parse("깃허브 MCP 서버 설치해줘")
        assert action == PackageAction.INSTALL

    def test_korean_search(self):
        action, _, _ = self.parser.parse("쿠버네티스 도구 검색")
        assert action == PackageAction.SEARCH

    def test_korean_remove(self):
        action, _, _ = self.parser.parse("슬랙 플러그인 제거")
        assert action == PackageAction.UNINSTALL

    def test_korean_list(self):
        action, _, _ = self.parser.parse("스킬 목록 보여줘")
        assert action == PackageAction.LIST

    def test_korean_type_detection(self):
        _, pkg_type, _ = self.parser.parse("쿠버네티스 도구 검색")
        assert pkg_type == PackageType.TOOL

    def test_korean_skill_type(self):
        _, pkg_type, _ = self.parser.parse("코드 리뷰 스킬 추가")
        assert pkg_type == PackageType.SKILL

    # --- Edge cases ---

    def test_empty_input(self):
        action, pkg_type, query = self.parser.parse("")
        assert action == PackageAction.SEARCH
        assert pkg_type is None

    def test_ambiguous_prefers_specific_action(self):
        # "install" is more specific than "find", so it wins
        action, _, _ = self.parser.parse("find and install a plugin")
        assert action == PackageAction.INSTALL


# ---------------------------------------------------------------------------
# PackageManager tests
# ---------------------------------------------------------------------------

@dataclass
class FakeSkill:
    name: str
    description: str = "A test skill"
    prompt_template: str = ""
    steps: list = field(default_factory=list)
    trigger_keywords: list = field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    source: str = "manual"


class TestPackageManagerSearch:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_search_skills(self, manager):
        skill_store = AsyncMock()
        skill = FakeSkill(name="code_review", description="Code review skill")
        skill_store.find_matching_skills = AsyncMock(return_value=[skill])
        manager.set_backends(skill_store=skill_store)

        results = await manager.search("code review", PackageType.SKILL)
        assert len(results) == 1
        assert results[0].name == "code_review"
        assert results[0].type == PackageType.SKILL

    async def test_search_mcp(self, manager):
        mcp_store = AsyncMock()
        mcp_store.search = AsyncMock(return_value=[
            {"name": "github", "slug": "github-mcp", "description": "GitHub MCP", "source": "clawhub"},
        ])
        manager.set_backends(mcp_store=mcp_store)

        results = await manager.search("github", PackageType.MCP_SERVER)
        assert len(results) == 1
        assert results[0].name == "github"
        assert results[0].type == PackageType.MCP_SERVER

    async def test_search_tools(self, manager):
        tool_registry = MagicMock()
        tool_def = MagicMock()
        tool_def.name = "shell_exec"
        tool_def.description = "Execute shell commands"
        tool_registry.get_all_definitions.return_value = [tool_def]
        tool_registry.get_tool_source.return_value = "builtin"
        manager.set_backends(tool_registry=tool_registry)

        results = await manager.search("shell", PackageType.TOOL)
        assert len(results) == 1
        assert results[0].name == "shell_exec"

    async def test_search_plugins(self, manager):
        plugin_manager = AsyncMock()
        manifest = MagicMock()
        manifest.name = "monitoring"
        manifest.version = "1.0.0"
        manifest.description = "Monitoring plugin"
        plugin_manager.discover = AsyncMock(return_value=[manifest])
        plugin_manager.loaded_plugins = {"monitoring": MagicMock()}
        manager.set_backends(plugin_manager=plugin_manager)

        results = await manager.search("monitoring", PackageType.PLUGIN)
        assert len(results) == 1
        assert results[0].name == "monitoring"
        assert results[0].status == "enabled"

    async def test_search_all_types(self, manager):
        """Search without type filter searches all backends."""
        skill_store = AsyncMock()
        skill_store.find_matching_skills = AsyncMock(return_value=[])
        mcp_store = AsyncMock()
        mcp_store.search = AsyncMock(return_value=[])
        tool_registry = MagicMock()
        tool_registry.get_all_definitions.return_value = []
        plugin_manager = AsyncMock()
        plugin_manager.discover = AsyncMock(return_value=[])
        plugin_manager.loaded_plugins = {}

        manager.set_backends(
            skill_store=skill_store,
            mcp_store=mcp_store,
            tool_registry=tool_registry,
            plugin_manager=plugin_manager,
        )

        results = await manager.search("anything")
        assert results == []
        skill_store.find_matching_skills.assert_awaited_once()
        mcp_store.search.assert_awaited_once()

    async def test_search_with_no_backends(self, manager):
        results = await manager.search("anything")
        assert results == []


class TestPackageManagerInstall:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_install_skill(self, manager):
        skill_store = AsyncMock()
        fake_skill = FakeSkill(name="review", source="package_manager")
        skill_store.add_skill = AsyncMock(return_value=fake_skill)
        manager.set_backends(skill_store=skill_store)

        result = await manager.install("review", PackageType.SKILL)
        assert result.success is True
        assert result.action == PackageAction.INSTALL
        assert result.package_type == PackageType.SKILL
        skill_store.add_skill.assert_awaited_once()

    async def test_install_skill_no_backend(self, manager):
        result = await manager.install("review", PackageType.SKILL)
        assert result.success is False
        assert "not supported" in result.message or "not available" in result.message

    async def test_install_mcp_server(self, manager):
        mcp_store = AsyncMock()
        mcp_store.search = AsyncMock(return_value=[
            {"name": "github", "slug": "github-mcp", "description": "GitHub", "source": "clawhub"},
        ])
        mcp_store.analyze_server = AsyncMock(return_value={
            "command": "node", "args": ["index.js"],
        })
        mcp_store.install_server = AsyncMock(return_value={
            "status": "ok", "name": "github", "tools": ["gh_search"], "tool_count": 1,
        })
        manager.set_backends(mcp_store=mcp_store)

        result = await manager.install("github", PackageType.MCP_SERVER)
        assert result.success is True
        assert "1 tools" in result.message

    async def test_install_mcp_not_found(self, manager):
        mcp_store = AsyncMock()
        mcp_store.search = AsyncMock(return_value=[])
        manager.set_backends(mcp_store=mcp_store)

        result = await manager.install("nonexistent", PackageType.MCP_SERVER)
        assert result.success is False
        assert "not found" in result.message

    async def test_install_plugin(self, manager):
        plugin_manager = AsyncMock()
        manifest = MagicMock()
        manifest.name = "my-plugin"
        manifest.version = "2.0.0"
        manifest.description = "My plugin"
        plugin_manager.install = AsyncMock(return_value=manifest)
        manager.set_backends(plugin_manager=plugin_manager)

        result = await manager.install("my-plugin", PackageType.PLUGIN)
        assert result.success is True
        assert "my-plugin" in result.message

    async def test_install_unsupported_type(self, manager):
        result = await manager.install("foo", PackageType.SEARCH_PROVIDER)
        assert result.success is False
        assert "not supported" in result.message


class TestPackageManagerUninstall:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_uninstall_skill(self, manager):
        skill_store = AsyncMock()
        skill_store.remove_skill = AsyncMock(return_value=True)
        manager.set_backends(skill_store=skill_store)

        result = await manager.uninstall("review", PackageType.SKILL)
        assert result.success is True

    async def test_uninstall_skill_not_found(self, manager):
        skill_store = AsyncMock()
        skill_store.remove_skill = AsyncMock(return_value=False)
        manager.set_backends(skill_store=skill_store)

        result = await manager.uninstall("nonexistent", PackageType.SKILL)
        assert result.success is False
        assert "not found" in result.message

    async def test_uninstall_mcp(self, manager):
        mcp_store = AsyncMock()
        mcp_store.remove_server = AsyncMock(return_value={"status": "ok"})
        manager.set_backends(mcp_store=mcp_store)

        result = await manager.uninstall("github", PackageType.MCP_SERVER)
        assert result.success is True

    async def test_uninstall_plugin(self, manager):
        plugin_manager = AsyncMock()
        plugin_manager.uninstall = AsyncMock()
        manager.set_backends(plugin_manager=plugin_manager)

        result = await manager.uninstall("my-plugin", PackageType.PLUGIN)
        assert result.success is True
        plugin_manager.uninstall.assert_awaited_once_with("my-plugin")

    async def test_uninstall_tool(self, manager):
        tool_registry = MagicMock()
        tool_registry.unregister.return_value = True
        manager.set_backends(tool_registry=tool_registry)

        result = await manager.uninstall("shell_exec", PackageType.TOOL)
        assert result.success is True


class TestPackageManagerEnableDisable:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_enable_plugin(self, manager):
        plugin_manager = AsyncMock()
        plugin_manager.load = AsyncMock(return_value=MagicMock())
        manager.set_backends(plugin_manager=plugin_manager)

        result = await manager.enable("my-plugin", PackageType.PLUGIN)
        assert result.success is True
        plugin_manager.load.assert_awaited_once_with("my-plugin")

    async def test_enable_plugin_not_found(self, manager):
        plugin_manager = AsyncMock()
        plugin_manager.load = AsyncMock(return_value=None)
        manager.set_backends(plugin_manager=plugin_manager)

        result = await manager.enable("nonexistent", PackageType.PLUGIN)
        assert result.success is False

    async def test_disable_plugin(self, manager):
        plugin_manager = AsyncMock()
        plugin_manager.unload = AsyncMock()
        manager.set_backends(plugin_manager=plugin_manager)

        result = await manager.disable("my-plugin", PackageType.PLUGIN)
        assert result.success is True
        plugin_manager.unload.assert_awaited_once_with("my-plugin")

    async def test_enable_tracked_package(self, manager):
        """Enable a package tracked internally (non-plugin)."""
        pkg = Package(name="review", type=PackageType.SKILL, status="disabled")
        manager._installed["review"] = pkg

        result = await manager.enable("review", PackageType.SKILL)
        assert result.success is True
        assert manager._installed["review"].status == "enabled"

    async def test_disable_tracked_package(self, manager):
        pkg = Package(name="review", type=PackageType.SKILL, status="enabled")
        manager._installed["review"] = pkg

        result = await manager.disable("review", PackageType.SKILL)
        assert result.success is True
        assert manager._installed["review"].status == "disabled"

    async def test_enable_nonexistent_package(self, manager):
        result = await manager.enable("ghost", PackageType.SKILL)
        assert result.success is False
        assert "not found" in result.message


class TestPackageManagerListAndStatus:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_list_packages_empty(self, manager):
        packages = await manager.list_packages()
        assert packages == []

    async def test_list_with_filter(self, manager):
        skill_store = AsyncMock()
        skill = FakeSkill(name="review", description="Code review")
        skill_store.list_skills = AsyncMock(return_value=[skill])
        manager.set_backends(skill_store=skill_store)

        packages = await manager.list_packages(PackageType.SKILL)
        assert len(packages) == 1
        assert packages[0].type == PackageType.SKILL

    async def test_list_with_status_filter(self, manager):
        tool_registry = MagicMock()
        tool_def = MagicMock()
        tool_def.name = "shell_exec"
        tool_def.description = "Execute shell"
        tool_registry.get_all_definitions.return_value = [tool_def]
        tool_registry.get_tool_source.return_value = "builtin"
        manager.set_backends(tool_registry=tool_registry)

        # "enabled" status should match
        packages = await manager.list_packages(PackageType.TOOL, status_filter="enabled")
        assert len(packages) == 1

        # "disabled" should return nothing
        packages = await manager.list_packages(PackageType.TOOL, status_filter="disabled")
        assert len(packages) == 0

    async def test_get_status(self, manager):
        skill_store = AsyncMock()
        skill_store.list_skills = AsyncMock(return_value=[
            FakeSkill(name="s1"), FakeSkill(name="s2"),
        ])
        manager.set_backends(skill_store=skill_store)

        status = await manager.get_status(PackageType.SKILL)
        assert "skill" in status
        assert status["skill"]["total"] == 2


class TestPackageManagerInfo:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_get_info_from_tracked(self, manager):
        pkg = Package(name="test", type=PackageType.SKILL, description="Test pkg")
        manager._installed["test"] = pkg

        result = await manager.get_info("test")
        assert result is not None
        assert result.name == "test"

    async def test_get_info_from_tool_registry(self, manager):
        tool_registry = MagicMock()
        tool_registry.has_tool.return_value = True
        tool_def = MagicMock()
        tool_def.name = "shell_exec"
        tool_def.description = "Execute shell commands"
        tool_registry.get_all_definitions.return_value = [tool_def]
        tool_registry.get_tool_source.return_value = "builtin"
        manager.set_backends(tool_registry=tool_registry)

        result = await manager.get_info("shell_exec")
        assert result is not None
        assert result.type == PackageType.TOOL

    async def test_get_info_from_skill_store(self, manager):
        skill_store = AsyncMock()
        skill = FakeSkill(name="review", description="Code review")
        skill_store.get_skill = AsyncMock(return_value=skill)
        tool_registry = MagicMock()
        tool_registry.has_tool.return_value = False
        manager.set_backends(skill_store=skill_store, tool_registry=tool_registry)

        result = await manager.get_info("review")
        assert result is not None
        assert result.type == PackageType.SKILL

    async def test_get_info_not_found(self, manager):
        result = await manager.get_info("nonexistent")
        assert result is None


class TestPackageManagerHandleMessage:
    @pytest.fixture
    def manager(self):
        return PackageManager()

    async def test_handle_search_message(self, manager):
        skill_store = AsyncMock()
        skill_store.find_matching_skills = AsyncMock(return_value=[])
        mcp_store = AsyncMock()
        mcp_store.search = AsyncMock(return_value=[])
        tool_registry = MagicMock()
        tool_registry.get_all_definitions.return_value = []
        plugin_manager = AsyncMock()
        plugin_manager.discover = AsyncMock(return_value=[])
        plugin_manager.loaded_plugins = {}
        manager.set_backends(
            skill_store=skill_store,
            mcp_store=mcp_store,
            tool_registry=tool_registry,
            plugin_manager=plugin_manager,
        )

        result = await manager.handle_message("Search for kubernetes tools")
        assert result.action == PackageAction.SEARCH
        assert result.success is True

    async def test_handle_install_with_type(self, manager):
        skill_store = AsyncMock()
        fake_skill = FakeSkill(name="review")
        skill_store.add_skill = AsyncMock(return_value=fake_skill)
        manager.set_backends(skill_store=skill_store)

        result = await manager.handle_message("Install a code review skill")
        assert result.action == PackageAction.INSTALL
        assert result.package_type == PackageType.SKILL

    async def test_handle_list_message(self, manager):
        result = await manager.handle_message("List all plugins")
        assert result.action == PackageAction.LIST

    async def test_handle_install_unknown_type(self, manager):
        result = await manager.handle_message("Install foobar123xyz")
        assert result.action == PackageAction.INSTALL
        # Type couldn't be determined from text or query
        # So it may fail or infer
        assert isinstance(result, PackageActionResult)


class TestPackageManagerInferType:
    def test_infer_mcp_from_server(self):
        pm = PackageManager()
        assert pm._infer_type("github server") == PackageType.MCP_SERVER

    def test_infer_plugin(self):
        pm = PackageManager()
        assert pm._infer_type("monitoring plugin") == PackageType.PLUGIN

    def test_infer_skill(self):
        pm = PackageManager()
        assert pm._infer_type("code review skill") == PackageType.SKILL

    def test_infer_none(self):
        pm = PackageManager()
        assert pm._infer_type("foobar123xyz") is None


class TestPackageManagerTracking:
    async def test_track_and_untrack(self):
        pm = PackageManager()
        pkg = Package(name="test", type=PackageType.SKILL)
        pm._track_installed(pkg)
        assert "test" in pm._installed

        pm._untrack("test")
        assert "test" not in pm._installed

    async def test_install_tracks_package(self):
        pm = PackageManager()
        skill_store = AsyncMock()
        fake_skill = FakeSkill(name="review", source="pm")
        skill_store.add_skill = AsyncMock(return_value=fake_skill)
        pm.set_backends(skill_store=skill_store)

        await pm.install("review", PackageType.SKILL)
        assert "review" in pm._installed

    async def test_uninstall_untracks_package(self):
        pm = PackageManager()
        pm._installed["review"] = Package(name="review", type=PackageType.SKILL)
        skill_store = AsyncMock()
        skill_store.remove_skill = AsyncMock(return_value=True)
        pm.set_backends(skill_store=skill_store)

        await pm.uninstall("review", PackageType.SKILL)
        assert "review" not in pm._installed
