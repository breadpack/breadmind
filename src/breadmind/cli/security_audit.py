"""Security audit tool: scans configuration, permissions, and common vulnerabilities."""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class AuditFinding:
    severity: Severity
    category: str  # "filesystem", "config", "network", "credentials", "plugins"
    message: str
    fix: str = ""  # suggested fix
    auto_fixable: bool = False


class SecurityAuditor:
    """Scans BreadMind configuration and environment for security issues."""

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = config_dir or os.path.join(Path.home().as_posix(), ".breadmind")
        self._findings: list[AuditFinding] = []

    def run_audit(self, deep: bool = False) -> list[AuditFinding]:
        self._findings = []
        self._check_filesystem_permissions()
        self._check_config_files()
        self._check_credential_exposure()
        self._check_env_vars()
        if deep:
            self._check_network_exposure()
            self._check_plugin_security()
        return sorted(self._findings, key=lambda f:
                      {"critical": 0, "warning": 1, "info": 2}[f.severity.value])

    def fix_findings(self) -> list[str]:
        """Apply auto-fixes for fixable findings."""
        fixed = []
        for finding in self._findings:
            if not finding.auto_fixable:
                continue
            if "permission" in finding.category and "chmod" in finding.fix:
                try:
                    path = finding.fix.split("'")[1] if "'" in finding.fix else ""
                    if path and os.path.exists(path):
                        os.chmod(path, 0o600)
                        fixed.append(f"Fixed: {finding.message}")
                except (OSError, IndexError):
                    pass
        return fixed

    def _check_filesystem_permissions(self) -> None:
        """Check file/directory permissions."""
        config_dir = self._config_dir
        if os.path.exists(config_dir):
            if sys.platform != "win32":
                try:
                    mode = os.stat(config_dir).st_mode
                    if mode & stat.S_IROTH or mode & stat.S_IWOTH:
                        self._findings.append(AuditFinding(
                            severity=Severity.CRITICAL,
                            category="filesystem",
                            message=f"Config directory {config_dir} is world-readable/writable",
                            fix=f"chmod 700 '{config_dir}'",
                            auto_fixable=True,
                        ))
                except OSError:
                    pass

        sensitive_patterns = ["*.key", "*.pem", ".env", "credentials*"]
        for pattern in sensitive_patterns:
            for f in Path(config_dir).glob(pattern) if os.path.isdir(config_dir) else []:
                if sys.platform != "win32":
                    try:
                        mode = os.stat(f).st_mode
                        if mode & stat.S_IROTH:
                            self._findings.append(AuditFinding(
                                severity=Severity.CRITICAL,
                                category="filesystem",
                                message=f"Sensitive file {f} is world-readable",
                                fix=f"chmod 600 '{f}'",
                                auto_fixable=True,
                            ))
                    except OSError:
                        pass

    def _check_config_files(self) -> None:
        """Check configuration for security issues."""
        config_path = os.path.join(self._config_dir, "config.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    content = f.read()
                secret_patterns = [
                    (r'api[_-]?key\s*[:=]\s*["\']?[a-zA-Z0-9]{20,}', "API key appears hardcoded"),
                    (r'password\s*[:=]\s*["\']?\S+', "Password appears hardcoded"),
                    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key found in config"),
                ]
                for pattern, msg in secret_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        self._findings.append(AuditFinding(
                            severity=Severity.CRITICAL,
                            category="credentials",
                            message=msg,
                            fix="Move secrets to .env file or environment variables",
                        ))
            except (IOError, OSError):
                pass

    def _check_credential_exposure(self) -> None:
        """Check for exposed credential files."""
        cred_dir = os.path.join(self._config_dir, "credentials")
        if os.path.isdir(cred_dir):
            for f in os.listdir(cred_dir):
                fpath = os.path.join(cred_dir, f)
                if os.path.isfile(fpath) and sys.platform != "win32":
                    try:
                        mode = os.stat(fpath).st_mode
                        if mode & (stat.S_IRGRP | stat.S_IROTH):
                            self._findings.append(AuditFinding(
                                severity=Severity.CRITICAL,
                                category="credentials",
                                message=f"Credential file {f} has loose permissions",
                                fix=f"chmod 600 '{fpath}'",
                                auto_fixable=True,
                            ))
                    except OSError:
                        pass

    def _check_env_vars(self) -> None:
        """Check environment variables for security issues."""
        dangerous_vars = {
            "BREADMIND_SSH_STRICT_HOST_KEY": ("false", "SSH host key verification is disabled"),
        }
        for var, (bad_val, msg) in dangerous_vars.items():
            if os.environ.get(var, "").lower() == bad_val:
                self._findings.append(AuditFinding(
                    severity=Severity.WARNING,
                    category="config",
                    message=msg,
                    fix=f"Unset {var} or set to 'true'",
                ))

    def _check_network_exposure(self) -> None:
        """Deep: check for network exposure."""
        config_path = os.path.join(self._config_dir, "config.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    content = f.read()
                if "0.0.0.0" in content:
                    self._findings.append(AuditFinding(
                        severity=Severity.WARNING,
                        category="network",
                        message="Server binds to 0.0.0.0 (all interfaces)",
                        fix="Bind to 127.0.0.1 for local-only access",
                    ))
            except (IOError, OSError):
                pass

    def _check_plugin_security(self) -> None:
        """Deep: check plugin configurations."""
        plugins_dir = os.path.join(self._config_dir, "plugins")
        if os.path.isdir(plugins_dir):
            for name in os.listdir(plugins_dir):
                manifest = os.path.join(plugins_dir, name, "plugin.json")
                if os.path.exists(manifest):
                    try:
                        with open(manifest) as f:
                            data = json.load(f)
                        if data.get("permissions", {}).get("network") == "*":
                            self._findings.append(AuditFinding(
                                severity=Severity.WARNING,
                                category="plugins",
                                message=f"Plugin '{name}' has unrestricted network access",
                            ))
                    except (json.JSONDecodeError, IOError):
                        pass

    def format_report(self, findings: list[AuditFinding] | None = None) -> str:
        """Format findings as a human-readable report."""
        findings = findings or self._findings
        if not findings:
            return "Security audit: No issues found."

        lines = [f"Security Audit Report ({len(findings)} findings):"]
        for f in findings:
            icon = {"critical": "[!]", "warning": "[~]", "info": "[i]"}[f.severity.value]
            lines.append(f"  {icon} [{f.severity.value.upper()}] {f.message}")
            if f.fix:
                lines.append(f"      Fix: {f.fix}")

        critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
        warnings = sum(1 for f in findings if f.severity == Severity.WARNING)
        lines.append(f"\nSummary: {critical} critical, {warnings} warnings")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps([
            {"severity": f.severity.value, "category": f.category,
             "message": f.message, "fix": f.fix, "auto_fixable": f.auto_fixable}
            for f in self._findings
        ], indent=2)
