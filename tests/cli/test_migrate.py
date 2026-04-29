"""Tests for breadmind migrate CLI subcommand.

Covers Click command registration (--help) plus behavioral checks that
verify each subcommand:
  - calls the underlying run_* helper with the right args
  - prints the documented success line
  - exits non-zero with an "Error" prefix when the helper raises
"""
from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from breadmind.cli.migrate import migrate as migrate_group


# --- Click registration smoke tests --------------------------------------


def test_migrate_up_command_exists():
    runner = CliRunner()
    result = runner.invoke(migrate_group, ["up", "--help"])
    assert result.exit_code == 0
    assert "Apply" in result.output or "upgrade" in result.output


def test_migrate_down_command_exists():
    runner = CliRunner()
    result = runner.invoke(migrate_group, ["down", "--help"])
    assert result.exit_code == 0


def test_migrate_stamp_command_exists():
    runner = CliRunner()
    result = runner.invoke(migrate_group, ["stamp", "--help"])
    assert result.exit_code == 0


def test_migrate_status_command_exists():
    runner = CliRunner()
    result = runner.invoke(migrate_group, ["status", "--help"])
    assert result.exit_code == 0


# --- Behavioral tests: `up` ----------------------------------------------


def test_migrate_up_calls_run_upgrade_and_prints_revision():
    runner = CliRunner()
    with patch("breadmind.cli.migrate.run_upgrade", return_value="abc123") as mock_up:
        result = runner.invoke(migrate_group, ["up"])
    assert result.exit_code == 0
    mock_up.assert_called_once_with("head")
    assert "Migrated to: abc123" in result.output


def test_migrate_up_error_exits_nonzero():
    runner = CliRunner()
    with patch("breadmind.cli.migrate.run_upgrade", side_effect=RuntimeError("boom")):
        result = runner.invoke(migrate_group, ["up"])
    assert result.exit_code == 1
    assert "Error" in result.output


# --- Behavioral tests: `down` --------------------------------------------


def test_migrate_down_calls_run_downgrade_with_steps():
    runner = CliRunner()
    with patch("breadmind.cli.migrate.run_downgrade", return_value="xyz789") as mock_down:
        result = runner.invoke(migrate_group, ["down", "2"])
    assert result.exit_code == 0
    mock_down.assert_called_once_with("-2")
    assert "Rolled back to: xyz789" in result.output


def test_migrate_down_error_exits_nonzero():
    runner = CliRunner()
    with patch(
        "breadmind.cli.migrate.run_downgrade",
        side_effect=RuntimeError("rollback failed"),
    ):
        result = runner.invoke(migrate_group, ["down", "1"])
    assert result.exit_code == 1
    assert "Error" in result.output


# --- Behavioral tests: `stamp` -------------------------------------------


def test_migrate_stamp_calls_run_stamp():
    runner = CliRunner()
    with patch("breadmind.cli.migrate.run_stamp") as mock_stamp:
        result = runner.invoke(migrate_group, ["stamp", "head"])
    assert result.exit_code == 0
    mock_stamp.assert_called_once_with("head")
    assert "Stamped at: head" in result.output


def test_migrate_stamp_error_exits_nonzero():
    runner = CliRunner()
    with patch(
        "breadmind.cli.migrate.run_stamp",
        side_effect=RuntimeError("stamp failed"),
    ):
        result = runner.invoke(migrate_group, ["stamp", "head"])
    assert result.exit_code == 1
    assert "Error" in result.output


# --- Behavioral tests: `status` ------------------------------------------


def test_migrate_status_prints_head_and_pending():
    runner = CliRunner()
    with (
        patch("breadmind.cli.migrate.current_head", return_value="rev1"),
        patch("breadmind.cli.migrate.pending_count", return_value=3),
    ):
        result = runner.invoke(migrate_group, ["status"])
    assert result.exit_code == 0
    assert "Current head: rev1" in result.output
    assert "Pending migrations: 3" in result.output


def test_migrate_status_error_exits_nonzero():
    runner = CliRunner()
    with patch(
        "breadmind.cli.migrate.current_head",
        side_effect=RuntimeError("DB down"),
    ):
        result = runner.invoke(migrate_group, ["status"])
    assert result.exit_code == 1
    assert "Error" in result.output


# --- Legacy: smoke that `status` against an unreachable DB doesn't crash -


def test_migrate_status_runs_without_error(tmp_path, monkeypatch):
    """`breadmind migrate status` should print or fail gracefully against an
    unreachable DB rather than crash with ImportError/AttributeError."""
    monkeypatch.setenv("BREADMIND_DB_URL", "postgresql://localhost/nonexistent")
    runner = CliRunner()
    result = runner.invoke(migrate_group, ["status"])
    assert "Error" in result.output or "head" in result.output or result.exit_code != 0
