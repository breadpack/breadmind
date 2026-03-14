import pytest
from pathlib import Path
from breadmind.config import load_config, MCPConfig, RegistryConfigItem

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
