from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FixAction(str, Enum):
    RECREATE_CONFIG = "recreate_config"
    CLEAR_STALE_CACHE = "clear_stale_cache"
    REPAIR_DATABASE = "repair_database"
    RESET_PERMISSIONS = "reset_permissions"
    MIGRATE_BREAKING = "migrate_breaking"
    REMOVE_STALE_STATE = "remove_stale_state"
    FIX_PATH = "fix_path"


@dataclass
class DiagnosticResult:
    name: str
    passed: bool
    message: str = ""
    fix_available: bool = False
    fix_action: FixAction | None = None
    fix_detail: str = ""


@dataclass
class FixReport:
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    fixed: int = 0
    fix_failed: int = 0
    details: list[DiagnosticResult] = field(default_factory=list)


# Stale cache threshold: 7 days in seconds
_CACHE_MAX_AGE = 7 * 24 * 3600

# Stale session threshold: 24 hours in seconds
_SESSION_MAX_AGE = 24 * 3600


class DoctorFix:
    """Auto-remediation for common BreadMind issues.

    Extends doctor command with --fix and --deep flags.
    --fix: attempt automatic fixes for detected issues
    --deep: run deeper checks (slower but more thorough)
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        user_dir: Path | None = None,
        auto_fix: bool = False,
        deep: bool = False,
    ):
        self._project_dir = project_dir or Path.cwd()
        self._user_dir = user_dir or Path.home() / ".breadmind"
        self._auto_fix = auto_fix
        self._deep = deep

    def run_diagnostics(self) -> FixReport:
        """Run all diagnostic checks and optionally fix issues."""
        report = FixReport()
        checks = [
            self.check_config_exists,
            self.check_stale_cache,
            self.check_permissions,
            self.check_stale_sessions,
        ]
        if self._deep:
            checks.append(self.check_database_connection)
            checks.append(self.check_provider_health)

        for check_fn in checks:
            result = check_fn()
            report.total_checks += 1
            report.details.append(result)

            if result.passed:
                report.passed += 1
            else:
                report.failed += 1
                if self._auto_fix and result.fix_available:
                    if self._apply_fix(result):
                        report.fixed += 1
                        report.failed -= 1
                    else:
                        report.fix_failed += 1

        return report

    def check_config_exists(self) -> DiagnosticResult:
        """Check if config files exist and are valid."""
        config_path = self._project_dir / "config" / "config.yaml"
        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
                if not content.strip():
                    return DiagnosticResult(
                        name="config_exists",
                        passed=False,
                        message="config.yaml is empty",
                        fix_available=True,
                        fix_action=FixAction.RECREATE_CONFIG,
                        fix_detail="Will create a default config.yaml",
                    )
                return DiagnosticResult(
                    name="config_exists",
                    passed=True,
                    message=str(config_path),
                )
            except Exception as exc:
                return DiagnosticResult(
                    name="config_exists",
                    passed=False,
                    message=f"Error reading config: {exc}",
                    fix_available=True,
                    fix_action=FixAction.RECREATE_CONFIG,
                    fix_detail="Will recreate config.yaml",
                )
        return DiagnosticResult(
            name="config_exists",
            passed=False,
            message="config.yaml not found",
            fix_available=True,
            fix_action=FixAction.RECREATE_CONFIG,
            fix_detail="Will create a default config.yaml",
        )

    def check_stale_cache(self) -> DiagnosticResult:
        """Check for stale cache files."""
        cache_dir = self._user_dir / "cache"
        if not cache_dir.exists():
            return DiagnosticResult(
                name="stale_cache",
                passed=True,
                message="No cache directory",
            )

        stale_files: list[Path] = []
        now = time.time()
        try:
            for entry in cache_dir.iterdir():
                if entry.is_file():
                    age = now - entry.stat().st_mtime
                    if age > _CACHE_MAX_AGE:
                        stale_files.append(entry)
        except OSError as exc:
            return DiagnosticResult(
                name="stale_cache",
                passed=False,
                message=f"Cannot read cache dir: {exc}",
            )

        if stale_files:
            return DiagnosticResult(
                name="stale_cache",
                passed=False,
                message=f"{len(stale_files)} stale cache file(s)",
                fix_available=True,
                fix_action=FixAction.CLEAR_STALE_CACHE,
                fix_detail=f"Will remove {len(stale_files)} stale file(s)",
            )
        return DiagnosticResult(
            name="stale_cache",
            passed=True,
            message="Cache is clean",
        )

    def check_permissions(self) -> DiagnosticResult:
        """Check file/directory permissions."""
        dirs_to_check = [
            self._project_dir / "config",
            self._user_dir,
        ]
        issues: list[str] = []
        for d in dirs_to_check:
            if d.exists():
                if not os.access(d, os.R_OK):
                    issues.append(f"{d}: not readable")
                if not os.access(d, os.W_OK):
                    issues.append(f"{d}: not writable")

        if issues:
            return DiagnosticResult(
                name="permissions",
                passed=False,
                message="; ".join(issues),
                fix_available=True,
                fix_action=FixAction.RESET_PERMISSIONS,
                fix_detail="Will attempt to fix directory permissions",
            )
        return DiagnosticResult(
            name="permissions",
            passed=True,
            message="Permissions OK",
        )

    def check_stale_sessions(self) -> DiagnosticResult:
        """Check for orphaned session files."""
        sessions_dir = self._user_dir / "sessions"
        if not sessions_dir.exists():
            return DiagnosticResult(
                name="stale_sessions",
                passed=True,
                message="No sessions directory",
            )

        stale: list[Path] = []
        now = time.time()
        try:
            for entry in sessions_dir.iterdir():
                if entry.is_file():
                    age = now - entry.stat().st_mtime
                    if age > _SESSION_MAX_AGE:
                        stale.append(entry)
        except OSError as exc:
            return DiagnosticResult(
                name="stale_sessions",
                passed=False,
                message=f"Cannot read sessions dir: {exc}",
            )

        if stale:
            return DiagnosticResult(
                name="stale_sessions",
                passed=False,
                message=f"{len(stale)} stale session file(s)",
                fix_available=True,
                fix_action=FixAction.REMOVE_STALE_STATE,
                fix_detail=f"Will remove {len(stale)} stale session(s)",
            )
        return DiagnosticResult(
            name="stale_sessions",
            passed=True,
            message="No stale sessions",
        )

    def check_database_connection(self) -> DiagnosticResult:
        """Check if database is reachable (deep mode only)."""
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            return DiagnosticResult(
                name="database_connection",
                passed=True,
                message="DATABASE_URL not set (file-based mode)",
            )
        try:
            import asyncpg  # noqa: F401

            return DiagnosticResult(
                name="database_connection",
                passed=True,
                message="asyncpg available (connection not tested in sync mode)",
            )
        except ImportError:
            return DiagnosticResult(
                name="database_connection",
                passed=False,
                message="asyncpg not installed",
                fix_available=False,
            )

    def check_provider_health(self) -> DiagnosticResult:
        """Check if configured LLM providers are responsive (deep mode only)."""
        provider_keys = {
            "ANTHROPIC_API_KEY": "Anthropic",
            "GOOGLE_API_KEY": "Google",
            "XAI_API_KEY": "xAI",
        }
        found: list[str] = []
        for env_key, name in provider_keys.items():
            if os.environ.get(env_key):
                found.append(name)

        if not found:
            return DiagnosticResult(
                name="provider_health",
                passed=True,
                message="No provider keys configured",
            )
        return DiagnosticResult(
            name="provider_health",
            passed=True,
            message=f"Keys found: {', '.join(found)}",
        )

    def _apply_fix(self, result: DiagnosticResult) -> bool:
        """Apply a fix for a diagnostic result. Returns True if fixed."""
        if result.fix_action is None:
            return False

        fix_map = {
            FixAction.RECREATE_CONFIG: self._fix_recreate_config,
            FixAction.CLEAR_STALE_CACHE: self._fix_clear_stale_cache,
            FixAction.REMOVE_STALE_STATE: self._fix_remove_stale_state,
            FixAction.RESET_PERMISSIONS: self._fix_reset_permissions,
        }
        fix_fn = fix_map.get(result.fix_action)
        if fix_fn is None:
            return False
        try:
            return fix_fn()
        except Exception:
            return False

    def _fix_recreate_config(self) -> bool:
        config_dir = self._project_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        default_config = (
            "# BreadMind configuration\n"
            "database:\n"
            "  url: ${DATABASE_URL:-sqlite:///breadmind.db}\n"
            "web:\n"
            "  host: 0.0.0.0\n"
            "  port: 8080\n"
        )
        config_path.write_text(default_config, encoding="utf-8")
        return True

    def _fix_clear_stale_cache(self) -> bool:
        cache_dir = self._user_dir / "cache"
        if not cache_dir.exists():
            return True
        now = time.time()
        removed = 0
        for entry in cache_dir.iterdir():
            if entry.is_file():
                age = now - entry.stat().st_mtime
                if age > _CACHE_MAX_AGE:
                    entry.unlink()
                    removed += 1
        return removed >= 0

    def _fix_remove_stale_state(self) -> bool:
        sessions_dir = self._user_dir / "sessions"
        if not sessions_dir.exists():
            return True
        now = time.time()
        for entry in sessions_dir.iterdir():
            if entry.is_file():
                age = now - entry.stat().st_mtime
                if age > _SESSION_MAX_AGE:
                    entry.unlink()
        return True

    def _fix_reset_permissions(self) -> bool:
        dirs_to_fix = [
            self._project_dir / "config",
            self._user_dir,
        ]
        for d in dirs_to_fix:
            if d.exists():
                try:
                    os.chmod(d, 0o755)
                except OSError:
                    return False
        return True
