"""Integration test: full plugin lifecycle — install, load, verify, unload, verify."""
from __future__ import annotations

import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_plugin_dir(base: Path, manifest_data: dict) -> Path:
    """Create a minimal plugin directory structure in *base*."""
    plugin_dir = base / manifest_data["name"]
    claude_plugin = plugin_dir / ".claude-plugin"
    claude_plugin.mkdir(parents=True)
    (claude_plugin / "plugin.json").write_text(
        json.dumps(manifest_data), encoding="utf-8"
    )
    return plugin_dir


LIFECYCLE_MANIFEST = {
    "name": "lifecycle-agent",
    "version": "1.0.0",
    "description": "Integration test plugin with a coding agent",
    "author": "test",
    "x-breadmind": {
        "coding_agents": [
            {
                "name": "lifecycle-cli",
                "cli_command": "lifecycle-cli",
                "prompt_flag": "-p",
                "cwd_flag": "--cwd",
                "output_format": "text",
            }
        ]
    },
}


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestPluginFullLifecycle:
    """End-to-end: create plugin dir → install → load → verify coding agent
    registered → unload → verify unregistered."""

    def _make_manager(self, tmp_path: Path):
        from breadmind.plugins.manager import PluginManager
        plugins_dir = tmp_path / "installed"
        plugins_dir.mkdir()
        return PluginManager(plugins_dir=plugins_dir)

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path):
        from breadmind.coding.adapters import get_adapter, unregister_adapter, _ADAPTERS

        # --- Step 1: Create source plugin directory ---
        source_dir = _make_plugin_dir(tmp_path / "sources", LIFECYCLE_MANIFEST)
        assert (source_dir / ".claude-plugin" / "plugin.json").exists(), \
            "plugin.json must exist before install"

        # --- Step 2: Install into manager ---
        manager = self._make_manager(tmp_path)
        manifest = await manager.install(str(source_dir))

        assert manifest.name == "lifecycle-agent"
        assert manifest.version == "1.0.0"
        installed_path = manager._plugins_dir / "lifecycle-agent"
        assert installed_path.exists(), "plugin directory must be copied into plugins_dir"

        # --- Step 3: Verify plugin is loaded ---
        assert "lifecycle-agent" in manager.loaded_plugins, \
            "plugin must appear in loaded_plugins after install"

        # --- Step 4: Verify coding agent registered ---
        try:
            adapter = get_adapter("lifecycle-cli")
            assert adapter.name == "lifecycle-cli", \
                "coding agent name must match manifest entry"
        finally:
            # Always clean up global adapter state
            unregister_adapter("lifecycle-cli")

        # --- Step 5: Unload the plugin ---
        await manager.unload("lifecycle-agent")
        assert "lifecycle-agent" not in manager.loaded_plugins, \
            "plugin must be removed from loaded_plugins after unload"

        # --- Step 6: Verify coding agent is unregistered ---
        assert "lifecycle-cli" not in _ADAPTERS, \
            "coding agent must be removed from _ADAPTERS after unload"

    @pytest.mark.asyncio
    async def test_install_then_uninstall_removes_files(self, tmp_path):
        """After uninstall, plugin directory should be gone from disk."""
        source_dir = _make_plugin_dir(tmp_path / "sources", LIFECYCLE_MANIFEST)
        manager = self._make_manager(tmp_path)

        await manager.install(str(source_dir))
        installed_path = manager._plugins_dir / "lifecycle-agent"
        assert installed_path.exists()

        # Clean up adapter registered during install
        from breadmind.coding.adapters import unregister_adapter
        unregister_adapter("lifecycle-cli")

        await manager.uninstall("lifecycle-agent")
        assert not installed_path.exists(), \
            "plugin directory must be deleted from disk after uninstall"
        assert "lifecycle-agent" not in manager.loaded_plugins

    @pytest.mark.asyncio
    async def test_builtin_plugin_loads_all_three_coding_agents(self, tmp_path):
        """The builtin coding-agents plugin must register claude, codex, and gemini."""
        from pathlib import Path as _Path
        from breadmind.plugins.manager import PluginManager
        from breadmind.coding.adapters import unregister_adapter, _ADAPTERS

        plugins_dir = tmp_path / "installed"
        plugins_dir.mkdir()
        manager = PluginManager(plugins_dir=plugins_dir)

        builtin_dir = _Path(__file__).resolve().parent.parent / "src" / "breadmind" / "plugins" / "builtin"
        coding_agents_dir = builtin_dir / "coding-agents"
        assert coding_agents_dir.exists(), \
            f"builtin coding-agents plugin directory must exist at {coding_agents_dir}"

        components = await manager.load_from_directory(coding_agents_dir)
        assert components is not None

        try:
            for agent_name in ("claude", "codex", "gemini"):
                assert agent_name in _ADAPTERS, \
                    f"'{agent_name}' must be registered after loading builtin plugin"
                adapter = _ADAPTERS[agent_name]
                assert adapter.name == agent_name
        finally:
            for agent_name in ("claude", "codex", "gemini"):
                unregister_adapter(agent_name)

    @pytest.mark.asyncio
    async def test_load_all_respects_disabled_flag(self, tmp_path):
        """load_all() must skip plugins marked as disabled in the registry."""
        from breadmind.coding.adapters import unregister_adapter

        source_dir = _make_plugin_dir(tmp_path / "sources", LIFECYCLE_MANIFEST)
        manager = self._make_manager(tmp_path)

        # Install (this loads it and registers the adapter)
        await manager.install(str(source_dir))
        unregister_adapter("lifecycle-cli")

        # Mark as disabled and unload
        await manager._registry.set_enabled("lifecycle-agent", False)
        await manager.unload("lifecycle-agent")

        # load_all() should not reload disabled plugins
        await manager.load_all()
        assert "lifecycle-agent" not in manager.loaded_plugins, \
            "disabled plugin must not be loaded by load_all()"
