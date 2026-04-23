from pathlib import Path

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.config import ConfigCheck

_VALID = """
migration_head: "006_connector_configs"
slack:
  required_channels: ["C01"]
  required_events: ["team_join"]
confluence:
  base_url: "https://x.atlassian.net/wiki"
  required_spaces: ["ENG"]
llm:
  anthropic:
    required_models: ["m"]
  azure:
    endpoint_env: "AZURE_OPENAI_ENDPOINT"
    required_deployments: ["d"]
  no_training_confirmed: true
"""


async def test_config_check_pass(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text(_VALID, encoding="utf-8")
    c = ConfigCheck(path=p)
    out = await c.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.PASS


async def test_config_check_fail_missing_file(tmp_path: Path):
    c = ConfigCheck(path=tmp_path / "nope.yaml")
    out = await c.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "not found" in out.detail
