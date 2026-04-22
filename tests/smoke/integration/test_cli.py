import subprocess
import sys
from pathlib import Path


def _invoke(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "breadmind", "smoke", *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def test_smoke_help(tmp_path: Path):
    r = _invoke("--help", cwd=tmp_path)
    assert r.returncode == 0
    assert "--targets" in r.stdout
    assert "--timeout" in r.stdout
    assert "--skip" in r.stdout


def test_smoke_missing_targets_is_exit_2(tmp_path: Path):
    r = _invoke("--targets", str(tmp_path / "nope.yaml"),
                "--skip", "database,vault,slack_auth,slack_channels,"
                          "slack_events,confluence_base_url,confluence_auth,"
                          "confluence_spaces,anthropic,azure_openai,llm_no_training",
                cwd=tmp_path)
    assert r.returncode == 2
    assert "not found" in (r.stdout + r.stderr).lower()
