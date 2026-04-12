"""Tests for hot-reload manager."""
from __future__ import annotations

from breadmind.plugins.hot_reload import (
    HotReloadManager,
    PluginInfo,
    PluginState,
)


def _make_manager_with_plugin(
    name: str = "test-plugin",
    tools: list[str] | None = None,
    **kwargs,
) -> tuple[HotReloadManager, PluginInfo]:
    mgr = HotReloadManager()
    info = mgr.register_plugin(name, tools=tools or ["tool_a", "tool_b"], **kwargs)
    return mgr, info


# ── register_plugin ─────────────────────────────────────────────────


def test_register_plugin_basic():
    mgr = HotReloadManager()
    info = mgr.register_plugin("my-plugin", tools=["t1"], version="1.0")
    assert info.name == "my-plugin"
    assert info.version == "1.0"
    assert info.state == PluginState.ENABLED
    assert info.tools_registered == ["t1"]


def test_register_plugin_defaults():
    mgr = HotReloadManager()
    info = mgr.register_plugin("bare")
    assert info.tools_registered == []
    assert info.skills_registered == []
    assert info.config == {}


def test_register_plugin_with_config():
    mgr = HotReloadManager()
    info = mgr.register_plugin("cfg", config={"key": "val"})
    assert info.config == {"key": "val"}


# ── enable / disable ────────────────────────────────────────────────


def test_disable_removes_tools():
    mgr, info = _make_manager_with_plugin()
    result = mgr.disable("test-plugin")
    assert result.success is True
    assert set(result.tools_removed) == {"tool_a", "tool_b"}
    assert mgr.get_state("test-plugin") == PluginState.DISABLED
    assert mgr.get_tools_for_plugin("test-plugin") == []


def test_enable_restores_tools():
    mgr, _ = _make_manager_with_plugin()
    mgr.disable("test-plugin")
    result = mgr.enable("test-plugin")
    assert result.success is True
    assert set(result.tools_added) == {"tool_a", "tool_b"}
    assert mgr.get_state("test-plugin") == PluginState.ENABLED
    assert set(mgr.get_tools_for_plugin("test-plugin")) == {"tool_a", "tool_b"}


def test_disable_already_disabled():
    mgr, _ = _make_manager_with_plugin()
    mgr.disable("test-plugin")
    result = mgr.disable("test-plugin")
    assert result.success is True
    assert "already disabled" in result.message


def test_enable_already_enabled():
    mgr, _ = _make_manager_with_plugin()
    result = mgr.enable("test-plugin")
    assert result.success is True
    assert "already enabled" in result.message


def test_enable_not_found():
    mgr = HotReloadManager()
    result = mgr.enable("missing")
    assert result.success is False
    assert "not found" in result.message


def test_disable_not_found():
    mgr = HotReloadManager()
    result = mgr.disable("missing")
    assert result.success is False


# ── reload ──────────────────────────────────────────────────────────


def test_reload_updates_config():
    mgr, _ = _make_manager_with_plugin(config={"old": True})
    result = mgr.reload("test-plugin", new_config={"new": True})
    assert result.success is True
    assert mgr.get_info("test-plugin").config == {"new": True}


def test_reload_not_found():
    mgr = HotReloadManager()
    result = mgr.reload("missing")
    assert result.success is False


def test_reload_preserves_config_when_none():
    mgr, _ = _make_manager_with_plugin(config={"keep": 1})
    result = mgr.reload("test-plugin")
    assert result.success is True
    assert mgr.get_info("test-plugin").config == {"keep": 1}


# ── update_config ───────────────────────────────────────────────────


def test_update_config_merges():
    mgr, _ = _make_manager_with_plugin(config={"a": 1})
    result = mgr.update_config("test-plugin", {"b": 2})
    assert result.success is True
    assert mgr.get_info("test-plugin").config == {"a": 1, "b": 2}


def test_update_config_not_found():
    mgr = HotReloadManager()
    result = mgr.update_config("missing", {"x": 1})
    assert result.success is False


# ── listing and queries ─────────────────────────────────────────────


def test_list_plugins_all():
    mgr = HotReloadManager()
    mgr.register_plugin("a")
    mgr.register_plugin("b")
    mgr.register_plugin("c")
    assert len(mgr.list_plugins()) == 3


def test_list_plugins_state_filter():
    mgr = HotReloadManager()
    mgr.register_plugin("a")
    mgr.register_plugin("b")
    mgr.disable("b")
    enabled = mgr.list_plugins(state_filter=PluginState.ENABLED)
    disabled = mgr.list_plugins(state_filter=PluginState.DISABLED)
    assert len(enabled) == 1
    assert len(disabled) == 1
    assert enabled[0].name == "a"
    assert disabled[0].name == "b"


def test_get_summary():
    mgr = HotReloadManager()
    mgr.register_plugin("a")
    mgr.register_plugin("b")
    mgr.register_plugin("c")
    mgr.disable("c")
    summary = mgr.get_summary()
    assert summary["total"] == 3
    assert summary["enabled"] == 2
    assert summary["disabled"] == 1
    assert summary["error"] == 0


def test_is_enabled():
    mgr, _ = _make_manager_with_plugin()
    assert mgr.is_enabled("test-plugin") is True
    mgr.disable("test-plugin")
    assert mgr.is_enabled("test-plugin") is False
    assert mgr.is_enabled("nonexistent") is False


def test_get_state_none_for_missing():
    mgr = HotReloadManager()
    assert mgr.get_state("nope") is None


def test_get_info_none_for_missing():
    mgr = HotReloadManager()
    assert mgr.get_info("nope") is None


def test_get_tools_for_missing_plugin():
    mgr = HotReloadManager()
    assert mgr.get_tools_for_plugin("nope") == []
