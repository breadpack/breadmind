"""Comprehensive tests for the BreadMind plugin system (Tasks 1-5)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plugin_dir(tmp_path: Path, manifest_data: dict, extra_files: dict | None = None) -> Path:
    """Create a minimal plugin directory structure."""
    plugin_dir = tmp_path / manifest_data["name"]
    claude_plugin = plugin_dir / ".claude-plugin"
    claude_plugin.mkdir(parents=True)
    (claude_plugin / "plugin.json").write_text(
        json.dumps(manifest_data), encoding="utf-8"
    )
    if extra_files:
        for rel_path, content in extra_files.items():
            full = plugin_dir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
    return plugin_dir


MINIMAL_MANIFEST = {"name": "test-plugin", "version": "1.0.0"}

FULL_MANIFEST = {
    "name": "full-plugin",
    "version": "2.0.0",
    "description": "A full plugin",
    "author": "Alice",
    "x-breadmind": {
        "coding_agents": [
            {
                "name": "mymcp",
                "cli_command": "mymcp",
                "prompt_flag": "--prompt",
                "cwd_flag": "--dir",
                "output_format": "json",
            }
        ],
        "roles": ["roles/my-role.md"],
        "tools": [{"name": "my_tool"}],
        "mcp_servers": "servers.json",
        "requires": {"python": ">=3.11"},
        "settings": {"timeout": 30},
    },
}


# ===========================================================================
# Task 1 — PluginManifest
# ===========================================================================

class TestPluginManifest:
    def test_from_dict_minimal(self):
        from breadmind.plugins.manifest import PluginManifest
        m = PluginManifest.from_dict(MINIMAL_MANIFEST)
        assert m.name == "test-plugin"
        assert m.version == "1.0.0"
        assert m.description == ""
        assert m.coding_agents == []
        assert m.tools == []
        assert m.plugin_dir is None
        assert m.enabled is True

    def test_from_dict_with_x_breadmind(self):
        from breadmind.plugins.manifest import PluginManifest
        m = PluginManifest.from_dict(FULL_MANIFEST)
        assert m.name == "full-plugin"
        assert m.version == "2.0.0"
        assert m.description == "A full plugin"
        assert m.author == "Alice"
        assert len(m.coding_agents) == 1
        assert m.coding_agents[0]["name"] == "mymcp"
        assert m.tools == [{"name": "my_tool"}]
        assert m.mcp_servers == "servers.json"
        assert m.requires == {"python": ">=3.11"}
        assert m.settings == {"timeout": 30}

    def test_from_dict_missing_name_raises(self):
        from breadmind.plugins.manifest import PluginManifest
        with pytest.raises(ValueError, match="name"):
            PluginManifest.from_dict({"version": "1.0.0"})

    def test_from_dict_missing_version_raises(self):
        from breadmind.plugins.manifest import PluginManifest
        with pytest.raises(ValueError, match="version"):
            PluginManifest.from_dict({"name": "x"})

    def test_from_directory(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        plugin_dir = make_plugin_dir(tmp_path, MINIMAL_MANIFEST)
        m = PluginManifest.from_directory(plugin_dir)
        assert m.name == "test-plugin"
        assert m.plugin_dir == plugin_dir

    def test_from_directory_missing_raises(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        with pytest.raises(FileNotFoundError):
            PluginManifest.from_directory(tmp_path / "nonexistent")


# ===========================================================================
# Task 2 — PluginRegistry
# ===========================================================================

class TestPluginRegistry:
    @pytest.mark.asyncio
    async def test_add_and_list_all(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        reg = PluginRegistry(tmp_path / "registry.json")
        await reg.add("plugin-a", {"version": "1.0.0", "enabled": True})
        result = await reg.list_all()
        assert "plugin-a" in result
        assert result["plugin-a"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_remove(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        reg = PluginRegistry(tmp_path / "registry.json")
        await reg.add("plugin-a", {"version": "1.0.0", "enabled": True})
        await reg.remove("plugin-a")
        result = await reg.list_all()
        assert "plugin-a" not in result

    @pytest.mark.asyncio
    async def test_get(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        reg = PluginRegistry(tmp_path / "registry.json")
        await reg.add("plugin-b", {"version": "2.0.0"})
        info = await reg.get("plugin-b")
        assert info is not None
        assert info["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        reg = PluginRegistry(tmp_path / "registry.json")
        info = await reg.get("nonexistent")
        assert info is None

    @pytest.mark.asyncio
    async def test_set_enabled(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        reg = PluginRegistry(tmp_path / "registry.json")
        await reg.add("plugin-c", {"version": "1.0.0", "enabled": True})
        await reg.set_enabled("plugin-c", False)
        info = await reg.get("plugin-c")
        assert info["enabled"] is False

    @pytest.mark.asyncio
    async def test_persists_to_disk(self, tmp_path):
        from breadmind.plugins.registry import PluginRegistry
        path = tmp_path / "registry.json"
        reg = PluginRegistry(path)
        await reg.add("plugin-d", {"version": "3.0.0"})
        # Re-load from disk
        reg2 = PluginRegistry(path)
        result = await reg2.list_all()
        assert "plugin-d" in result


# ===========================================================================
# Task 3 — DeclarativeAdapter + register/unregister
# ===========================================================================

class TestDeclarativeAdapter:
    def _make_adapter(self, **overrides):
        from breadmind.plugins.declarative_adapter import DeclarativeAdapter
        config = {
            "name": "mytool",
            "cli_command": "mytool",
            "prompt_flag": "-p",
            "cwd_flag": "--cwd",
            "output_format": "text",
            **overrides,
        }
        return DeclarativeAdapter(config)

    def test_build_command_basic(self):
        adapter = self._make_adapter()
        cmd = adapter.build_command("/my/project", "do something")
        assert cmd[0] == "mytool"
        assert "-p" in cmd
        assert "do something" in cmd
        assert "--cwd" in cmd
        assert "/my/project" in cmd

    def test_build_command_with_session(self):
        adapter = self._make_adapter(session_flag="--session", output_format="text")
        cmd = adapter.build_command("/proj", "fix bug", options={"session_id": "abc123"})
        assert "--session" in cmd
        assert "abc123" in cmd

    def test_build_command_with_model(self):
        adapter = self._make_adapter(model_flag="--model")
        cmd = adapter.build_command("/proj", "review code", options={"model": "gpt-4"})
        assert "--model" in cmd
        assert "gpt-4" in cmd

    def test_build_command_json_output(self):
        adapter = self._make_adapter(output_format="json")
        cmd = adapter.build_command("/proj", "task")
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_build_command_quiet_output(self):
        adapter = self._make_adapter(output_format="quiet")
        cmd = adapter.build_command("/proj", "task")
        assert "--quiet" in cmd

    def test_build_command_extra_flags(self):
        adapter = self._make_adapter(extra_flags=["--verbose", "--debug"])
        cmd = adapter.build_command("/proj", "task")
        assert "--verbose" in cmd
        assert "--debug" in cmd

    def test_parse_result_json_success(self):
        adapter = self._make_adapter(output_format="json")
        stdout = json.dumps({
            "result": "done",
            "files_changed": ["a.py"],
            "session_id": "sess1",
            "cost": {"total": 0.01},
        })
        result = adapter.parse_result(stdout, "", 0)
        assert result.success is True
        assert result.output == "done"
        assert result.files_changed == ["a.py"]
        assert result.session_id == "sess1"
        assert result.agent == "mytool"

    def test_parse_result_text_fallback(self):
        adapter = self._make_adapter(output_format="text")
        result = adapter.parse_result("some output", "", 0)
        assert result.success is True
        assert result.output == "some output"
        assert result.files_changed == []

    def test_parse_result_failure(self):
        adapter = self._make_adapter()
        result = adapter.parse_result("", "error occurred", 1)
        assert result.success is False
        assert result.output == "error occurred"

    def test_parse_result_json_invalid_falls_back(self):
        adapter = self._make_adapter(output_format="json")
        result = adapter.parse_result("not-json", "", 0)
        # Falls back to text mode
        assert result.success is True
        assert result.output == "not-json"


class TestRegisterUnregisterAdapter:
    def test_register_adapter(self):
        from breadmind.coding.adapters import register_adapter, get_adapter, unregister_adapter
        from breadmind.plugins.declarative_adapter import DeclarativeAdapter
        adapter = DeclarativeAdapter({"name": "custom-agent", "cli_command": "custom"})
        register_adapter("custom-agent", adapter)
        assert get_adapter("custom-agent") is adapter
        # cleanup
        unregister_adapter("custom-agent")

    def test_unregister_adapter(self):
        from breadmind.coding.adapters import register_adapter, get_adapter, unregister_adapter
        from breadmind.plugins.declarative_adapter import DeclarativeAdapter
        adapter = DeclarativeAdapter({"name": "temp-agent", "cli_command": "temp"})
        register_adapter("temp-agent", adapter)
        unregister_adapter("temp-agent")
        with pytest.raises(ValueError):
            get_adapter("temp-agent")

    def test_unregister_nonexistent_is_safe(self):
        from breadmind.coding.adapters import unregister_adapter
        # Should not raise
        unregister_adapter("does-not-exist-xyz")


# ===========================================================================
# Task 4 — PluginLoader
# ===========================================================================

class TestPluginLoader:
    def test_load_with_commands_dir(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        plugin_dir = make_plugin_dir(tmp_path, MINIMAL_MANIFEST, {
            "commands/greet.md": "---\ndescription: Say hello\n---\nHello world",
        })
        manifest = PluginManifest.from_directory(plugin_dir)
        loader = PluginLoader()
        components = loader.load(manifest)

        assert len(components.commands) == 1
        cmd = components.commands[0]
        assert cmd["name"] == "greet"
        assert cmd["description"] == "Say hello"
        assert "Hello world" in cmd["content"]

    def test_load_with_skills_dir(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        plugin_dir = make_plugin_dir(tmp_path, MINIMAL_MANIFEST, {
            "skills/search.md": "Search skill content",
        })
        manifest = PluginManifest.from_directory(plugin_dir)
        components = PluginLoader().load(manifest)

        assert len(components.skills) == 1
        assert components.skills[0]["name"] == "search"
        assert components.skills[0]["content"] == "Search skill content"

    def test_load_with_agents_dir(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        plugin_dir = make_plugin_dir(tmp_path, MINIMAL_MANIFEST, {
            "agents/my-agent.md": "Agent content",
        })
        manifest = PluginManifest.from_directory(plugin_dir)
        components = PluginLoader().load(manifest)

        assert len(components.agents) == 1
        assert components.agents[0]["name"] == "my-agent"

    def test_load_coding_agents(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader
        from breadmind.plugins.declarative_adapter import DeclarativeAdapter

        plugin_dir = make_plugin_dir(tmp_path, FULL_MANIFEST)
        manifest = PluginManifest.from_directory(plugin_dir)
        components = PluginLoader().load(manifest)

        assert len(components.coding_agents) == 1
        assert isinstance(components.coding_agents[0], DeclarativeAdapter)
        assert components.coding_agents[0].name == "mymcp"

    def test_load_empty_plugin(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        plugin_dir = make_plugin_dir(tmp_path, MINIMAL_MANIFEST)
        manifest = PluginManifest.from_directory(plugin_dir)
        components = PluginLoader().load(manifest)

        assert components.commands == []
        assert components.skills == []
        assert components.agents == []
        assert components.hooks == []
        assert components.coding_agents == []

    def test_load_no_plugin_dir(self):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        manifest = PluginManifest.from_dict(MINIMAL_MANIFEST)
        # plugin_dir is None → empty components
        components = PluginLoader().load(manifest)
        assert components.commands == []

    def test_load_tools_from_x_breadmind(self, tmp_path):
        from breadmind.plugins.manifest import PluginManifest
        from breadmind.plugins.loader import PluginLoader

        plugin_dir = make_plugin_dir(tmp_path, FULL_MANIFEST)
        manifest = PluginManifest.from_directory(plugin_dir)
        components = PluginLoader().load(manifest)

        assert components.tools == [{"name": "my_tool"}]


# ===========================================================================
# Task 5 — PluginManager
# ===========================================================================

class TestPluginManager:
    def _make_manager(self, tmp_path: Path):
        from breadmind.plugins.manager import PluginManager
        plugins_dir = tmp_path / "plugins"
        return PluginManager(plugins_dir)

    @pytest.mark.asyncio
    async def test_discover_finds_plugins(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, MINIMAL_MANIFEST)
        manifests = await manager.discover()
        assert len(manifests) == 1
        assert manifests[0].name == "test-plugin"

    @pytest.mark.asyncio
    async def test_discover_empty(self, tmp_path):
        manager = self._make_manager(tmp_path)
        manifests = await manager.discover()
        assert manifests == []

    @pytest.mark.asyncio
    async def test_load_plugin(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, MINIMAL_MANIFEST)
        components = await manager.load("test-plugin")
        assert components is not None
        assert "test-plugin" in manager.loaded_plugins

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        manager = self._make_manager(tmp_path)
        result = await manager.load("no-such-plugin")
        assert result is None

    @pytest.mark.asyncio
    async def test_unload_plugin(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, MINIMAL_MANIFEST)
        await manager.load("test-plugin")
        assert "test-plugin" in manager.loaded_plugins
        await manager.unload("test-plugin")
        assert "test-plugin" not in manager.loaded_plugins

    @pytest.mark.asyncio
    async def test_install_from_local_directory(self, tmp_path):
        manager = self._make_manager(tmp_path)
        source_dir = make_plugin_dir(tmp_path / "sources", MINIMAL_MANIFEST)
        manifest = await manager.install(str(source_dir))
        assert manifest.name == "test-plugin"
        assert "test-plugin" in manager.loaded_plugins
        # Plugin should be copied into plugins_dir
        assert (manager._plugins_dir / "test-plugin" / ".claude-plugin" / "plugin.json").exists()

    @pytest.mark.asyncio
    async def test_install_unknown_source_raises(self, tmp_path):
        manager = self._make_manager(tmp_path)
        with pytest.raises(ValueError, match="Unknown install source"):
            await manager.install("unknown-format")

    @pytest.mark.asyncio
    async def test_uninstall_plugin(self, tmp_path):
        manager = self._make_manager(tmp_path)
        source_dir = make_plugin_dir(tmp_path / "sources", MINIMAL_MANIFEST)
        await manager.install(str(source_dir))
        await manager.uninstall("test-plugin")
        assert "test-plugin" not in manager.loaded_plugins
        assert not (manager._plugins_dir / "test-plugin").exists()

    @pytest.mark.asyncio
    async def test_load_all(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, MINIMAL_MANIFEST)
        make_plugin_dir(manager._plugins_dir, {"name": "second-plugin", "version": "1.0.0"})
        await manager.load_all()
        assert "test-plugin" in manager.loaded_plugins
        assert "second-plugin" in manager.loaded_plugins

    @pytest.mark.asyncio
    async def test_load_all_skips_disabled(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, MINIMAL_MANIFEST)
        # Pre-register as disabled
        await manager._registry.add("test-plugin", {"version": "1.0.0", "enabled": False})
        await manager.load_all()
        assert "test-plugin" not in manager.loaded_plugins

    @pytest.mark.asyncio
    async def test_load_registers_coding_agent(self, tmp_path):
        from breadmind.coding.adapters import get_adapter, unregister_adapter
        manager = self._make_manager(tmp_path)
        # requires 에 "python" 서비스가 필요하므로 컨테이너에 등록
        manager.container.register("python", True)
        make_plugin_dir(manager._plugins_dir, FULL_MANIFEST)
        await manager.load("full-plugin")
        try:
            adapter = get_adapter("mymcp")
            assert adapter.name == "mymcp"
        finally:
            unregister_adapter("mymcp")

    @pytest.mark.asyncio
    async def test_unload_unregisters_coding_agent(self, tmp_path):
        from breadmind.coding.adapters import get_adapter
        manager = self._make_manager(tmp_path)
        manager.container.register("python", True)
        make_plugin_dir(manager._plugins_dir, FULL_MANIFEST)
        await manager.load("full-plugin")
        await manager.unload("full-plugin")
        with pytest.raises(ValueError):
            get_adapter("mymcp")

    def test_get_settings(self, tmp_path):
        manager = self._make_manager(tmp_path)
        make_plugin_dir(manager._plugins_dir, FULL_MANIFEST)
        settings = manager.get_settings("full-plugin")
        assert settings == {"timeout": 30}

    def test_get_settings_nonexistent_returns_empty(self, tmp_path):
        manager = self._make_manager(tmp_path)
        settings = manager.get_settings("no-such-plugin")
        assert settings == {}
