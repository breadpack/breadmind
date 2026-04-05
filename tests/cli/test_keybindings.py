"""Tests for customizable keybindings."""

from __future__ import annotations

import json
from pathlib import Path

from breadmind.cli.keybindings import (
    DEFAULT_KEYBINDINGS,
    Keybinding,
    KeybindingManager,
)


class TestDefaults:
    def test_default_bindings_loaded(self):
        mgr = KeybindingManager(config_path=Path("/nonexistent/kb.json"))
        bindings = mgr.list_bindings()
        assert len(bindings) == len(DEFAULT_KEYBINDINGS)

    def test_get_default_action(self):
        mgr = KeybindingManager(config_path=Path("/nonexistent/kb.json"))
        assert mgr.get_action("ctrl+c", "global") == "cancel"
        assert mgr.get_action("ctrl+o", "chat") == "compact"


class TestLoad:
    def test_load_user_overrides(self, tmp_path: Path):
        config = tmp_path / "kb.json"
        config.write_text(json.dumps([
            {"key": "ctrl+k", "action": "cancel", "context": "global"},
        ]))
        mgr = KeybindingManager(config_path=config)
        mgr.load()
        # ctrl+k should now be cancel instead of ctrl+c
        assert mgr.get_action("ctrl+k", "global") == "cancel"
        # ctrl+c should no longer be bound to cancel
        assert mgr.get_action("ctrl+c", "global") is None

    def test_load_missing_file_keeps_defaults(self, tmp_path: Path):
        mgr = KeybindingManager(config_path=tmp_path / "nope.json")
        mgr.load()
        assert len(mgr.list_bindings()) == len(DEFAULT_KEYBINDINGS)

    def test_load_invalid_json_keeps_defaults(self, tmp_path: Path):
        config = tmp_path / "bad.json"
        config.write_text("{{{not json")
        mgr = KeybindingManager(config_path=config)
        mgr.load()
        assert len(mgr.list_bindings()) == len(DEFAULT_KEYBINDINGS)


class TestSetBinding:
    def test_set_new_binding(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        mgr.set_binding("ctrl+d", "debug", "chat")
        assert mgr.get_action("ctrl+d", "chat") == "debug"

    def test_set_updates_existing(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        mgr.set_binding("ctrl+k", "cancel", "global")
        assert mgr.get_action("ctrl+k", "global") == "cancel"


class TestSave:
    def test_save_and_reload(self, tmp_path: Path):
        config = tmp_path / "kb.json"
        mgr = KeybindingManager(config_path=config)
        mgr.set_binding("ctrl+d", "debug", "chat")
        mgr.save()

        # Reload from disk
        mgr2 = KeybindingManager(config_path=config)
        mgr2.load()
        assert mgr2.get_action("ctrl+d", "chat") == "debug"

    def test_save_creates_parent_dir(self, tmp_path: Path):
        config = tmp_path / "subdir" / "kb.json"
        mgr = KeybindingManager(config_path=config)
        mgr.save()
        assert config.is_file()


class TestListBindings:
    def test_list_all(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        assert len(mgr.list_bindings()) == len(DEFAULT_KEYBINDINGS)

    def test_list_by_context(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        global_bindings = mgr.list_bindings(context="global")
        assert all(b.context == "global" for b in global_bindings)
        assert len(global_bindings) >= 2  # ctrl+c, ctrl+l, ctrl+shift+p


class TestGetActionContextFallback:
    def test_no_match_returns_none(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        assert mgr.get_action("f12", "chat") is None

    def test_case_insensitive_key(self):
        mgr = KeybindingManager(config_path=Path("/tmp/kb.json"))
        assert mgr.get_action("Ctrl+C", "global") == "cancel"
