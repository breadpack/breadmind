"""Tests for environment-based configuration profiles."""


import yaml

from breadmind.core.config_profiles import (
    get_active_env,
    get_profile_path,
    load_with_profile,
    merge_configs,
)


class TestGetActiveEnv:
    def test_get_active_env_default(self, monkeypatch):
        monkeypatch.delenv("BREADMIND_ENV", raising=False)
        assert get_active_env() == "development"

    def test_get_active_env_from_env_var(self, monkeypatch):
        monkeypatch.setenv("BREADMIND_ENV", "production")
        assert get_active_env() == "production"


class TestMergeConfigs:
    def test_merge_configs_simple(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = merge_configs(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_configs_nested(self):
        base = {"logging": {"level": "INFO", "format": "json"}, "web": {"port": 8080}}
        override = {"logging": {"level": "DEBUG"}}
        result = merge_configs(base, override)
        assert result == {
            "logging": {"level": "DEBUG", "format": "json"},
            "web": {"port": 8080},
        }

    def test_merge_configs_list_override(self):
        base = {"cors_origins": ["http://localhost:8080"]}
        override = {"cors_origins": ["*"]}
        result = merge_configs(base, override)
        assert result == {"cors_origins": ["*"]}


class TestGetProfilePath:
    def test_get_profile_path_exists(self, tmp_path):
        profile = tmp_path / "config.staging.yaml"
        profile.write_text("logging:\n  level: WARNING\n")
        result = get_profile_path(str(tmp_path), "staging")
        assert result == str(profile)

    def test_get_profile_path_not_exists(self, tmp_path):
        result = get_profile_path(str(tmp_path), "staging")
        assert result is None


class TestLoadWithProfile:
    def test_load_with_profile_base_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BREADMIND_ENV", "production")
        base_cfg = {"logging": {"level": "INFO"}, "web": {"port": 8080}}
        (tmp_path / "config.yaml").write_text(yaml.dump(base_cfg))
        # No config.production.yaml exists
        result = load_with_profile(str(tmp_path))
        assert result == base_cfg

    def test_load_with_profile_with_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BREADMIND_ENV", "production")
        base_cfg = {"logging": {"level": "INFO", "format": "text"}, "web": {"port": 8080}}
        override_cfg = {"logging": {"level": "WARNING", "format": "json"}}
        (tmp_path / "config.yaml").write_text(yaml.dump(base_cfg))
        (tmp_path / "config.production.yaml").write_text(yaml.dump(override_cfg))
        result = load_with_profile(str(tmp_path))
        assert result == {
            "logging": {"level": "WARNING", "format": "json"},
            "web": {"port": 8080},
        }
