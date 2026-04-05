"""Tests for bare mode (reproducible CI/headless runs)."""

from __future__ import annotations

from breadmind.cli.bare_mode import BareConfig, BareMode


class TestBareConfig:
    def test_defaults(self):
        cfg = BareConfig()
        assert cfg.skip_user_config is True
        assert cfg.skip_auto_memory is True
        assert cfg.skip_plugins is True
        assert cfg.skip_rules is True
        assert cfg.minimal_prompt is True
        assert cfg.allowed_tools is None


class TestBareModeDisabled:
    def test_all_loading_enabled_when_disabled(self):
        bm = BareMode(enabled=False)
        assert bm.should_load_user_config() is True
        assert bm.should_load_memory() is True
        assert bm.should_load_plugins() is True
        assert bm.should_load_rules() is True
        assert bm.should_use_minimal_prompt() is False

    def test_filter_tools_passthrough(self):
        bm = BareMode(enabled=False)
        tools = ["shell", "file", "git"]
        assert bm.filter_tools(tools) == tools


class TestBareModeEnabled:
    def test_all_loading_disabled_when_enabled(self):
        bm = BareMode(enabled=True)
        assert bm.should_load_user_config() is False
        assert bm.should_load_memory() is False
        assert bm.should_load_plugins() is False
        assert bm.should_load_rules() is False
        assert bm.should_use_minimal_prompt() is True

    def test_filter_tools_with_allowed_list(self):
        cfg = BareConfig(allowed_tools=["shell", "file"])
        bm = BareMode(enabled=True, config=cfg)
        tools = ["shell", "file", "git", "browser"]
        assert bm.filter_tools(tools) == ["shell", "file"]

    def test_filter_tools_no_restriction(self):
        cfg = BareConfig(allowed_tools=None)
        bm = BareMode(enabled=True, config=cfg)
        tools = ["shell", "file"]
        assert bm.filter_tools(tools) == tools


class TestBareModePartialConfig:
    def test_selective_skip(self):
        cfg = BareConfig(skip_plugins=False, skip_rules=False)
        bm = BareMode(enabled=True, config=cfg)
        assert bm.should_load_plugins() is True
        assert bm.should_load_rules() is True
        assert bm.should_load_user_config() is False
        assert bm.should_load_memory() is False


class TestProperties:
    def test_enabled_property(self):
        bm = BareMode(enabled=True)
        assert bm.enabled is True

    def test_config_property(self):
        cfg = BareConfig(skip_plugins=False)
        bm = BareMode(enabled=True, config=cfg)
        assert bm.config is cfg
