"""Shared fixtures for smoke tests."""
from __future__ import annotations

from pathlib import Path

import pytest


_VALID_TARGETS_YAML = """
migration_head: "006_connector_configs"
slack:
  required_channels: ["C01ABC"]
  required_events: ["team_join"]
confluence:
  base_url: "https://company.atlassian.net/wiki"
  required_spaces: ["ENG"]
llm:
  anthropic:
    required_models: ["claude-sonnet-4-6"]
  azure:
    endpoint_env: "AZURE_OPENAI_ENDPOINT"
    required_deployments: ["gpt-4o"]
  no_training_confirmed: true
"""


@pytest.fixture
def valid_targets_file(tmp_path: Path) -> Path:
    p = tmp_path / "pilot-targets.yaml"
    p.write_text(_VALID_TARGETS_YAML, encoding="utf-8")
    return p
