from pathlib import Path

import pytest

from breadmind.smoke.targets import (
    PilotTargets,
    TargetsError,
    load_targets,
)

_VALID = """
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


def test_load_valid(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text(_VALID, encoding="utf-8")
    t = load_targets(p)
    assert isinstance(t, PilotTargets)
    assert t.migration_head == "006_connector_configs"
    assert t.slack.required_channels == ["C01ABC"]
    assert t.confluence.base_url == "https://company.atlassian.net/wiki"
    assert t.llm.anthropic.required_models == ["claude-sonnet-4-6"]
    assert t.llm.azure.required_deployments == ["gpt-4o"]
    assert t.llm.no_training_confirmed is True


def test_rejects_unknown_top_level_key(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text(_VALID + "\nbogus: 1\n", encoding="utf-8")
    with pytest.raises(TargetsError) as ei:
        load_targets(p)
    assert "unknown" in str(ei.value).lower()


def test_rejects_missing_migration_head(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text(_VALID.replace('migration_head: "006_connector_configs"', ""),
                 encoding="utf-8")
    with pytest.raises(TargetsError):
        load_targets(p)


def test_rejects_missing_file(tmp_path: Path):
    with pytest.raises(TargetsError):
        load_targets(tmp_path / "nope.yaml")
