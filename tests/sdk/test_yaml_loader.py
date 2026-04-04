import pytest
from pathlib import Path
from breadmind.dsl.yaml_loader import load_agent_yaml

SAMPLE_YAML = """\
name: TestAgent
config:
  provider: claude
  model: claude-sonnet-4-6
  max_turns: 15

prompt:
  persona: friendly
  language: en
  role: k8s_expert

memory:
  working: true
  episodic: true
  dream: true

tools:
  include: [shell_exec, file_read, k8s_pods_list]
  approve_required: [shell_exec]

safety:
  autonomy: confirm-destructive
  blocked_patterns:
    - "rm -rf /"
"""

MINIMAL_YAML = """\
name: MinimalBot
"""


@pytest.fixture
def sample_yaml_file(tmp_path):
    p = tmp_path / "agent.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")
    return p


@pytest.fixture
def minimal_yaml_file(tmp_path):
    p = tmp_path / "minimal.yaml"
    p.write_text(MINIMAL_YAML, encoding="utf-8")
    return p


def test_load_full_yaml(sample_yaml_file):
    agent = load_agent_yaml(sample_yaml_file)
    assert agent.name == "TestAgent"
    assert agent.config.provider == "claude"
    assert agent.config.max_turns == 15
    assert agent.prompt.language == "en"
    assert agent.prompt.role == "k8s_expert"
    assert agent.memory_config.episodic is True
    assert agent.memory_config.dream is True
    assert "shell_exec" in agent.tools
    assert agent.safety_config.autonomy == "confirm-destructive"
    assert "rm -rf /" in agent.safety_config.blocked_patterns


def test_load_minimal_yaml(minimal_yaml_file):
    agent = load_agent_yaml(minimal_yaml_file)
    assert agent.name == "MinimalBot"
    assert agent.config.provider == "claude"
    assert agent.config.max_turns == 10


def test_load_approve_required(sample_yaml_file):
    agent = load_agent_yaml(sample_yaml_file)
    assert "shell_exec" in agent.safety_config.approve_required
