"""Tests for the 4-tier settings scope hierarchy."""

from __future__ import annotations

import json
from pathlib import Path


from breadmind.core.settings_hierarchy import (
    SettingsHierarchy,
    SettingsScope,
)


class TestSettingsScope:
    def test_scope_ordering(self):
        assert SettingsScope.USER < SettingsScope.PROJECT
        assert SettingsScope.PROJECT < SettingsScope.LOCAL
        assert SettingsScope.LOCAL < SettingsScope.MANAGED

    def test_scope_values(self):
        assert SettingsScope.USER == 0
        assert SettingsScope.MANAGED == 3


class TestSetScope:
    def test_set_and_get_scalar(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"llm": {"provider": "claude"}})
        assert h.get("llm.provider") == "claude"

    def test_higher_scope_wins_scalar(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"llm": {"provider": "claude"}})
        h.set_scope(SettingsScope.PROJECT, {"llm": {"provider": "gemini"}})
        assert h.get("llm.provider") == "gemini"

    def test_managed_always_wins(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"safety": {"mode": "permissive"}})
        h.set_scope(SettingsScope.LOCAL, {"safety": {"mode": "relaxed"}})
        h.set_scope(SettingsScope.MANAGED, {"safety": {"mode": "strict"}})
        assert h.get("safety.mode") == "strict"


class TestLoadScope:
    def test_load_from_file(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"web": {"port": 9090}}))

        h = SettingsHierarchy()
        h.load_scope(SettingsScope.USER, settings_file)
        assert h.get("web.port") == 9090

    def test_load_missing_file_is_noop(self, tmp_path: Path):
        h = SettingsHierarchy()
        h.load_scope(SettingsScope.USER, tmp_path / "nonexistent.json")
        assert h.get("anything") is None

    def test_load_invalid_json_is_noop(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json{{{")

        h = SettingsHierarchy()
        h.load_scope(SettingsScope.USER, bad_file)
        assert h.get("anything") is None


class TestArrayKeys:
    def test_array_keys_concatenated(self):
        h = SettingsHierarchy()
        h.set_scope(
            SettingsScope.USER,
            {"permissions": {"allow": ["read", "write"]}},
        )
        h.set_scope(
            SettingsScope.PROJECT,
            {"permissions": {"allow": ["execute"]}},
        )
        result = h.get("permissions.allow")
        assert set(result) == {"read", "write", "execute"}

    def test_array_keys_deduplicated(self):
        h = SettingsHierarchy()
        h.set_scope(
            SettingsScope.USER,
            {"permissions": {"deny": ["rm", "shutdown"]}},
        )
        h.set_scope(
            SettingsScope.PROJECT,
            {"permissions": {"deny": ["rm", "reboot"]}},
        )
        result = h.get("permissions.deny")
        assert result == ["rm", "shutdown", "reboot"]

    def test_array_key_default_when_empty(self):
        h = SettingsHierarchy()
        assert h.get("permissions.allow", []) == []


class TestIsManaged:
    def test_is_managed_true(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.MANAGED, {"safety": {"mode": "strict"}})
        assert h.is_managed("safety.mode") is True

    def test_is_managed_false_when_not_set(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"safety": {"mode": "relaxed"}})
        assert h.is_managed("safety.mode") is False

    def test_is_managed_false_when_no_managed_scope(self):
        h = SettingsHierarchy()
        assert h.is_managed("anything") is False


class TestResolveAll:
    def test_resolve_merges_all_layers(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"a": 1, "b": 2})
        h.set_scope(SettingsScope.PROJECT, {"b": 3, "c": 4})
        h.set_scope(SettingsScope.MANAGED, {"d": 5})
        result = h.resolve_all()
        assert result == {"a": 1, "b": 3, "c": 4, "d": 5}

    def test_resolve_deep_merge(self):
        h = SettingsHierarchy()
        h.set_scope(SettingsScope.USER, {"llm": {"provider": "claude", "model": "opus"}})
        h.set_scope(SettingsScope.PROJECT, {"llm": {"model": "sonnet"}})
        result = h.resolve_all()
        assert result["llm"]["provider"] == "claude"
        assert result["llm"]["model"] == "sonnet"


class TestGetDefault:
    def test_default_returned_when_key_missing(self):
        h = SettingsHierarchy()
        assert h.get("nonexistent.key", "fallback") == "fallback"

    def test_default_none_when_not_specified(self):
        h = SettingsHierarchy()
        assert h.get("nonexistent") is None


class TestLoadDefault:
    def test_load_default_with_managed_env(self, tmp_path: Path, monkeypatch):
        managed_file = tmp_path / "managed.json"
        managed_file.write_text(json.dumps({"enterprise": True}))
        monkeypatch.setenv("BREADMIND_MANAGED_SETTINGS", str(managed_file))

        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "settings.json").write_text(json.dumps({"theme": "dark"}))

        h = SettingsHierarchy.load_default(user_dir=user_dir, project_dir=tmp_path)
        assert h.get("enterprise") is True
        assert h.get("theme") == "dark"
