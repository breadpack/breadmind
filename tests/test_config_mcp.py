import pytest
from pathlib import Path
from breadmind.config import load_config, MCPConfig, RegistryConfigItem, AppConfig, LLMConfig, DatabaseConfig


def test_mcp_config_defaults():
    cfg = MCPConfig()
    assert cfg.auto_discover is True
    assert cfg.max_restart_attempts == 3
    assert cfg.servers == {}
    assert len(cfg.registries) == 2


def test_load_config_with_mcp(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
llm:
  default_provider: ollama
mcp:
  auto_discover: false
  max_restart_attempts: 5
  servers:
    my-server:
      transport: sse
      url: http://localhost:3001/sse
  registries:
    - name: clawhub
      type: clawhub
      enabled: true
""")
    cfg = load_config(str(tmp_path))
    assert cfg.mcp.auto_discover is False
    assert cfg.mcp.max_restart_attempts == 5
    assert "my-server" in cfg.mcp.servers
    assert cfg.mcp.servers["my-server"]["transport"] == "sse"


def test_load_config_without_mcp(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
llm:
  default_provider: ollama
""")
    cfg = load_config(str(tmp_path))
    assert cfg.mcp.auto_discover is True
    assert cfg.mcp.max_restart_attempts == 3


# --- Config validation tests ---

def test_validate_default_config():
    """Default config is valid."""
    cfg = AppConfig()
    cfg.validate()  # Should not raise


def test_validate_valid_providers():
    for provider in ("claude", "ollama", "cli"):
        cfg = AppConfig(llm=LLMConfig(default_provider=provider))
        cfg.validate()


def test_validate_invalid_provider():
    cfg = AppConfig(llm=LLMConfig(default_provider="gpt4"))
    with pytest.raises(ValueError, match="Invalid default_provider"):
        cfg.validate()


def test_validate_tool_call_max_turns_zero():
    cfg = AppConfig(llm=LLMConfig(tool_call_max_turns=0))
    with pytest.raises(ValueError, match="tool_call_max_turns must be >= 1"):
        cfg.validate()


def test_validate_tool_call_max_turns_negative():
    cfg = AppConfig(llm=LLMConfig(tool_call_max_turns=-5))
    with pytest.raises(ValueError, match="tool_call_max_turns must be >= 1"):
        cfg.validate()


def test_validate_tool_call_timeout_zero():
    cfg = AppConfig(llm=LLMConfig(tool_call_timeout_seconds=0))
    with pytest.raises(ValueError, match="tool_call_timeout_seconds must be >= 1"):
        cfg.validate()


def test_validate_database_port_zero():
    cfg = AppConfig(database=DatabaseConfig(port=0))
    with pytest.raises(ValueError, match="Database port"):
        cfg.validate()


def test_validate_database_port_too_high():
    cfg = AppConfig(database=DatabaseConfig(port=70000))
    with pytest.raises(ValueError, match="Database port"):
        cfg.validate()


def test_validate_database_port_negative():
    cfg = AppConfig(database=DatabaseConfig(port=-1))
    with pytest.raises(ValueError, match="Database port"):
        cfg.validate()


def test_validate_database_port_valid_boundaries():
    for port in (1, 5432, 65535):
        cfg = AppConfig(database=DatabaseConfig(port=port))
        cfg.validate()  # Should not raise
