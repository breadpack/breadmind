"""Tests for companion config load/save."""

from __future__ import annotations

from pathlib import Path

from breadmind.companion.config import CompanionConfig, load_config, save_config


def test_config_defaults():
    config = CompanionConfig()
    assert config.heartbeat_interval == 30
    assert config.reconnect_max_backoff == 300
    assert config.agent_id.startswith("companion-")
    assert config.device_name != ""


def test_config_explicit_values():
    config = CompanionConfig(
        commander_url="ws://localhost:8081/ws/agent",
        agent_id="test-companion",
        device_name="my-laptop",
    )
    assert config.commander_url == "ws://localhost:8081/ws/agent"
    assert config.agent_id == "test-companion"
    assert config.device_name == "my-laptop"


def test_config_save_and_load(tmp_path: Path):
    config = CompanionConfig(
        commander_url="ws://example.com/ws/agent",
        agent_id="save-test",
        device_name="dev-machine",
        heartbeat_interval=60,
        capabilities={"companion_screenshot": True},
    )
    path = tmp_path / "config.yaml"
    save_config(config, path)
    assert path.exists()

    loaded = load_config(path)
    assert loaded.commander_url == "ws://example.com/ws/agent"
    assert loaded.agent_id == "save-test"
    assert loaded.device_name == "dev-machine"
    assert loaded.heartbeat_interval == 60
    assert loaded.capabilities.get("companion_screenshot") is True


def test_load_missing_config(tmp_path: Path):
    config = load_config(tmp_path / "nonexistent.yaml")
    assert isinstance(config, CompanionConfig)
    assert config.commander_url == ""
