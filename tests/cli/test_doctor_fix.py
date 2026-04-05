"""Tests for doctor --fix auto-remediation."""

import os
import time

import pytest

from breadmind.cli.doctor_fix import (
    DiagnosticResult,
    DoctorFix,
    FixAction,
    FixReport,
    _CACHE_MAX_AGE,
    _SESSION_MAX_AGE,
)


@pytest.fixture
def tmp_dirs(tmp_path):
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    return project, user


def test_check_config_exists_missing(tmp_dirs):
    project, user = tmp_dirs
    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_config_exists()
    assert not result.passed
    assert result.fix_available
    assert result.fix_action == FixAction.RECREATE_CONFIG


def test_check_config_exists_present(tmp_dirs):
    project, user = tmp_dirs
    config_dir = project / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("web:\n  port: 8080\n")
    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_config_exists()
    assert result.passed


def test_check_config_exists_empty(tmp_dirs):
    project, user = tmp_dirs
    config_dir = project / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("")
    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_config_exists()
    assert not result.passed
    assert result.fix_available


def test_check_stale_cache_no_dir(tmp_dirs):
    project, user = tmp_dirs
    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_stale_cache()
    assert result.passed


def test_check_stale_cache_with_stale_files(tmp_dirs):
    project, user = tmp_dirs
    cache_dir = user / "cache"
    cache_dir.mkdir()
    stale_file = cache_dir / "old.cache"
    stale_file.write_text("data")
    # Set mtime to 8 days ago
    old_time = time.time() - (_CACHE_MAX_AGE + 3600)
    os.utime(stale_file, (old_time, old_time))

    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_stale_cache()
    assert not result.passed
    assert result.fix_available
    assert result.fix_action == FixAction.CLEAR_STALE_CACHE


def test_check_stale_sessions_with_stale(tmp_dirs):
    project, user = tmp_dirs
    sessions_dir = user / "sessions"
    sessions_dir.mkdir()
    stale = sessions_dir / "sess_abc123.json"
    stale.write_text("{}")
    old_time = time.time() - (_SESSION_MAX_AGE + 3600)
    os.utime(stale, (old_time, old_time))

    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_stale_sessions()
    assert not result.passed
    assert result.fix_action == FixAction.REMOVE_STALE_STATE


def test_check_permissions_ok(tmp_dirs):
    project, user = tmp_dirs
    (project / "config").mkdir()
    doc = DoctorFix(project_dir=project, user_dir=user)
    result = doc.check_permissions()
    assert result.passed


def test_fix_recreate_config(tmp_dirs):
    project, user = tmp_dirs
    doc = DoctorFix(project_dir=project, user_dir=user, auto_fix=True)
    result = doc._fix_recreate_config()
    assert result is True
    config_path = project / "config" / "config.yaml"
    assert config_path.exists()
    content = config_path.read_text()
    assert "database:" in content


def test_fix_clear_stale_cache(tmp_dirs):
    project, user = tmp_dirs
    cache_dir = user / "cache"
    cache_dir.mkdir()
    stale = cache_dir / "old.cache"
    stale.write_text("data")
    old_time = time.time() - (_CACHE_MAX_AGE + 3600)
    os.utime(stale, (old_time, old_time))
    fresh = cache_dir / "new.cache"
    fresh.write_text("fresh")

    doc = DoctorFix(project_dir=project, user_dir=user, auto_fix=True)
    doc._fix_clear_stale_cache()
    assert not stale.exists()
    assert fresh.exists()


def test_fix_remove_stale_state(tmp_dirs):
    project, user = tmp_dirs
    sessions_dir = user / "sessions"
    sessions_dir.mkdir()
    stale = sessions_dir / "old_session.json"
    stale.write_text("{}")
    old_time = time.time() - (_SESSION_MAX_AGE + 3600)
    os.utime(stale, (old_time, old_time))

    doc = DoctorFix(project_dir=project, user_dir=user, auto_fix=True)
    doc._fix_remove_stale_state()
    assert not stale.exists()


def test_run_diagnostics_basic(tmp_dirs):
    project, user = tmp_dirs
    (project / "config").mkdir()
    (project / "config" / "config.yaml").write_text("web:\n  port: 8080\n")

    doc = DoctorFix(project_dir=project, user_dir=user)
    report = doc.run_diagnostics()
    assert isinstance(report, FixReport)
    assert report.total_checks == 4
    assert report.passed >= 1


def test_run_diagnostics_with_auto_fix(tmp_dirs):
    project, user = tmp_dirs
    # No config — should be detected and fixed
    doc = DoctorFix(project_dir=project, user_dir=user, auto_fix=True)
    report = doc.run_diagnostics()
    assert report.fixed >= 1
    assert (project / "config" / "config.yaml").exists()


def test_run_diagnostics_deep_mode(tmp_dirs):
    project, user = tmp_dirs
    (project / "config").mkdir()
    (project / "config" / "config.yaml").write_text("ok: true\n")
    doc = DoctorFix(project_dir=project, user_dir=user, deep=True)
    report = doc.run_diagnostics()
    # Deep adds 2 more checks
    assert report.total_checks == 6


def test_check_database_no_dsn(tmp_dirs, monkeypatch):
    project, user = tmp_dirs
    monkeypatch.delenv("DATABASE_URL", raising=False)
    doc = DoctorFix(project_dir=project, user_dir=user, deep=True)
    result = doc.check_database_connection()
    assert result.passed


def test_check_provider_health_no_keys(tmp_dirs, monkeypatch):
    project, user = tmp_dirs
    for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    doc = DoctorFix(project_dir=project, user_dir=user, deep=True)
    result = doc.check_provider_health()
    assert result.passed
    assert "No provider keys" in result.message
