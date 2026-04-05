"""Tests for security audit CLI tool."""
from __future__ import annotations

import json
import os
import stat
from unittest.mock import patch

import pytest

from breadmind.cli.security_audit import AuditFinding, SecurityAuditor, Severity


def test_no_findings_clean_env(tmp_path):
    """Clean environment should produce no findings."""
    auditor = SecurityAuditor(config_dir=str(tmp_path / "nonexistent"))
    findings = auditor.run_audit()
    assert findings == []


def test_detects_world_readable_config(tmp_path):
    """Should detect world-readable config directory on non-win32."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Mock os.stat to return world-readable permissions and sys.platform to linux
    fake_stat = os.stat_result((0o40777, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    with patch("breadmind.cli.security_audit.sys") as mock_sys, \
         patch("breadmind.cli.security_audit.os.stat", return_value=fake_stat):
        mock_sys.platform = "linux"
        auditor = SecurityAuditor(config_dir=str(config_dir))
        findings = auditor.run_audit()

    fs_findings = [f for f in findings if f.category == "filesystem"]
    assert len(fs_findings) >= 1
    assert fs_findings[0].severity == Severity.CRITICAL
    assert "world-readable" in fs_findings[0].message


def test_detects_hardcoded_api_key(tmp_path):
    """Should detect hardcoded API keys in config.yaml."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text("api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890")

    auditor = SecurityAuditor(config_dir=str(config_dir))
    findings = auditor.run_audit()

    cred_findings = [f for f in findings if f.category == "credentials"]
    assert len(cred_findings) >= 1
    assert any("API key" in f.message or "OpenAI" in f.message for f in cred_findings)


def test_env_var_warnings():
    """Should warn about dangerous environment variable settings."""
    with patch.dict(os.environ, {"BREADMIND_SSH_STRICT_HOST_KEY": "false"}):
        auditor = SecurityAuditor(config_dir="/nonexistent")
        findings = auditor.run_audit()

    config_findings = [f for f in findings if f.category == "config"]
    assert len(config_findings) == 1
    assert "SSH" in config_findings[0].message
    assert config_findings[0].severity == Severity.WARNING


def test_network_exposure_detection(tmp_path):
    """Deep audit should detect 0.0.0.0 binding."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text("host: 0.0.0.0\nport: 8080")

    auditor = SecurityAuditor(config_dir=str(config_dir))
    findings = auditor.run_audit(deep=True)

    net_findings = [f for f in findings if f.category == "network"]
    assert len(net_findings) == 1
    assert "0.0.0.0" in net_findings[0].message


def test_fix_permissions(tmp_path):
    """fix_findings should call os.chmod for auto-fixable findings."""
    target_file = tmp_path / "secret.key"
    target_file.write_text("secret")

    auditor = SecurityAuditor(config_dir=str(tmp_path))
    # Manually inject a fixable finding
    auditor._findings = [
        AuditFinding(
            severity=Severity.CRITICAL,
            category="filesystem_permission",
            message="File has loose permissions",
            fix=f"chmod 600 '{target_file}'",
            auto_fixable=True,
        )
    ]

    with patch("breadmind.cli.security_audit.os.chmod") as mock_chmod:
        fixed = auditor.fix_findings()

    assert len(fixed) == 1
    mock_chmod.assert_called_once_with(str(target_file), 0o600)


def test_format_report():
    """format_report should produce readable output."""
    auditor = SecurityAuditor(config_dir="/nonexistent")
    auditor._findings = [
        AuditFinding(Severity.CRITICAL, "credentials", "API key exposed", fix="Remove it"),
        AuditFinding(Severity.WARNING, "network", "Open port"),
    ]

    report = auditor.format_report()
    assert "2 findings" in report
    assert "[CRITICAL]" in report
    assert "[WARNING]" in report
    assert "1 critical, 1 warnings" in report
    assert "Fix:" in report


def test_to_json():
    """to_json should return valid JSON with all findings."""
    auditor = SecurityAuditor(config_dir="/nonexistent")
    auditor._findings = [
        AuditFinding(Severity.CRITICAL, "credentials", "Key found", fix="Remove", auto_fixable=False),
        AuditFinding(Severity.WARNING, "config", "Bad setting"),
    ]

    data = json.loads(auditor.to_json())
    assert len(data) == 2
    assert data[0]["severity"] == "critical"
    assert data[0]["category"] == "credentials"
    assert data[1]["severity"] == "warning"
