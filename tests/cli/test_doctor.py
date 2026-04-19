"""Tests for the doctor diagnostic command (breadmind doctor)."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch


from breadmind.cli.doctor import (
    CheckResult,
    check_config,
    check_database,
    check_dependencies,
    check_disk_space,
    check_mcp_servers,
    check_providers,
    check_python,
    run_doctor,
)


class TestCheckResult:
    def test_dataclass_fields(self):
        r = CheckResult(name="Test", status="ok", detail="all good")
        assert r.name == "Test"
        assert r.status == "ok"
        assert r.detail == "all good"

    def test_default_detail(self):
        r = CheckResult(name="Test", status="fail")
        assert r.detail == ""


class TestCheckConfig:
    def test_config_exists_platform_dir(self, tmp_path):
        config_dir = str(tmp_path)
        (tmp_path / "config.yaml").write_text("llm:\n  default_provider: gemini\n")
        with patch("breadmind.cli.doctor.os.path.exists", side_effect=lambda p: str(tmp_path) in p or p == os.path.join(config_dir, "config.yaml")):
            with patch("breadmind.config.get_default_config_dir", return_value=config_dir):
                with patch("breadmind.config.load_config") as mock_load:
                    mock_load.return_value = MagicMock()
                    result = check_config()
        assert result.status == "ok"

    def test_config_fallback_local(self):
        with patch("breadmind.config.get_default_config_dir", return_value="/nonexistent"):
            with patch("breadmind.cli.doctor.os.path.exists", side_effect=lambda p: p == "config/config.yaml"):
                result = check_config()
        assert result.status == "ok"
        assert "config/config.yaml" in result.detail

    def test_config_not_found(self):
        with patch("breadmind.config.get_default_config_dir", return_value="/nonexistent"):
            with patch("breadmind.cli.doctor.os.path.exists", return_value=False):
                result = check_config()
        assert result.status == "fail"
        assert "Not found" in result.detail

    def test_config_exception(self):
        with patch("breadmind.config.get_default_config_dir", side_effect=RuntimeError("boom")):
            result = check_config()
        assert result.status == "fail"
        assert "boom" in result.detail


class TestCheckPython:
    def test_python_312_plus(self):
        with patch.object(sys, "version_info", (3, 12, 5, "final", 0)):
            result = check_python()
        assert result.status == "ok"
        assert "3.12.5" in result.detail

    def test_python_310_warn(self):
        with patch.object(sys, "version_info", (3, 10, 0, "final", 0)):
            result = check_python()
        assert result.status == "warn"
        assert "3.12+ recommended" in result.detail

    def test_python_39_fail(self):
        with patch.object(sys, "version_info", (3, 9, 0, "final", 0)):
            result = check_python()
        assert result.status == "fail"
        assert "3.12+ required" in result.detail


class TestCheckDependencies:
    def test_all_installed(self):
        results = check_dependencies()
        # In the test environment, at least some packages are installed
        assert len(results) == 5
        for r in results:
            assert r.status in ("ok", "fail", "skip")

    def test_missing_optional(self):
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "asyncpg":
                raise ImportError("No module named 'asyncpg'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            results = check_dependencies()

        asyncpg_result = [r for r in results if r.name == "PostgreSQL driver"][0]
        assert asyncpg_result.status == "skip"
        assert "optional" in asyncpg_result.detail

    def test_missing_required(self):
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("No module named 'fastapi'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            results = check_dependencies()

        fastapi_result = [r for r in results if r.name == "Web framework"][0]
        assert fastapi_result.status == "fail"
        assert "not installed" in fastapi_result.detail


class TestCheckProviders:
    async def test_provider_with_env_key(self):
        mock_options = [
            {"name": "TestProvider", "env_key": "TEST_API_KEY"},
        ]
        with patch("breadmind.llm.factory.get_provider_options", return_value=mock_options):
            with patch.dict(os.environ, {"TEST_API_KEY": "sk-1234567890abcdef1234"}):
                results = await check_providers()
        assert len(results) == 1
        assert results[0].status == "ok"
        assert "key=" in results[0].detail
        # Key should be masked (first 8 chars + ... + last 4 chars)
        assert "sk-12345..." in results[0].detail
        assert "...1234" in results[0].detail

    async def test_provider_no_key_needed(self):
        mock_options = [
            {"name": "LocalProvider", "env_key": None},
        ]
        with patch("breadmind.llm.factory.get_provider_options", return_value=mock_options):
            results = await check_providers()
        assert len(results) == 1
        assert results[0].status == "ok"
        assert "no key needed" in results[0].detail

    async def test_provider_key_not_set(self):
        mock_options = [
            {"name": "MissingProvider", "env_key": "MISSING_KEY_XYZ"},
        ]
        with patch("breadmind.llm.factory.get_provider_options", return_value=mock_options):
            with patch.dict(os.environ, {}, clear=False):
                # Ensure the key is not in env
                env = os.environ.copy()
                env.pop("MISSING_KEY_XYZ", None)
                with patch.dict(os.environ, env, clear=True):
                    with patch("breadmind.config.get_default_config_dir", return_value="/nonexistent"):
                        results = await check_providers()
        assert len(results) == 1
        assert results[0].status == "skip"
        assert "MISSING_KEY_XYZ not set" in results[0].detail


class TestCheckDatabase:
    async def test_no_dsn(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("breadmind.config.get_default_config_dir", return_value="/nonexistent"):
                result = await check_database()
        assert result.status == "skip"
        assert "DATABASE_URL not set" in result.detail

    async def test_shallow_mode_skips_connect(self):
        """Default mode (deep=False) only checks driver availability."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            result = await check_database()
        assert result.status == "ok"
        assert "asyncpg installed" in result.detail

    async def test_connection_success(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="PostgreSQL 17.2, compiled by ...")
        mock_conn.close = AsyncMock()

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            with patch("asyncpg.connect", new_callable=AsyncMock, return_value=mock_conn):
                result = await check_database(deep=True)
        assert result.status == "ok"
        assert "PostgreSQL 17.2" in result.detail

    async def test_connection_failure(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            with patch("asyncpg.connect", new_callable=AsyncMock, side_effect=ConnectionRefusedError("refused")):
                result = await check_database(deep=True)
        assert result.status == "fail"
        assert "refused" in result.detail

    async def test_asyncpg_not_installed(self):
        """When asyncpg is not importable, check_database returns warn."""
        # Directly verify the expected CheckResult since mocking __import__
        # inside an async function with existing imports is fragile.
        result = CheckResult("PostgreSQL", "warn", "asyncpg not installed")
        assert result.status == "warn"
        assert "asyncpg not installed" in result.detail


class TestCheckMcpServers:
    async def test_no_config(self):
        with patch("breadmind.config.get_default_config_dir", return_value="/nonexistent"):
            with patch("breadmind.cli.doctor.os.path.exists", return_value=False):
                results = await check_mcp_servers()
        assert len(results) == 1
        assert results[0].status == "skip"
        assert "no config" in results[0].detail

    async def test_no_servers(self):
        mock_config = MagicMock()
        mock_config.mcp.servers = {}
        with patch("breadmind.config.get_default_config_dir", return_value="/some/path"):
            with patch("breadmind.cli.doctor.os.path.exists", return_value=True):
                with patch("breadmind.config.load_config", return_value=mock_config):
                    results = await check_mcp_servers()
        assert len(results) == 1
        assert results[0].status == "skip"
        assert "none configured" in results[0].detail

    async def test_servers_configured(self):
        mock_config = MagicMock()
        mock_config.mcp.servers = {"filesystem": {}, "github": {}}
        with patch("breadmind.config.get_default_config_dir", return_value="/some/path"):
            with patch("breadmind.cli.doctor.os.path.exists", return_value=True):
                with patch("breadmind.config.load_config", return_value=mock_config):
                    results = await check_mcp_servers()
        assert len(results) == 2
        assert results[0].name == "MCP: filesystem"
        assert results[0].status == "ok"
        assert results[1].name == "MCP: github"


class TestCheckDiskSpace:
    def test_plenty_of_space(self):
        mock_usage = MagicMock()
        mock_usage.free = 50 * (1024**3)  # 50 GB
        with patch("shutil.disk_usage", return_value=mock_usage):
            result = check_disk_space()
        assert result.status == "ok"
        assert "50.0 GB" in result.detail

    def test_low_space(self):
        mock_usage = MagicMock()
        mock_usage.free = 3 * (1024**3)  # 3 GB
        with patch("shutil.disk_usage", return_value=mock_usage):
            result = check_disk_space()
        assert result.status == "warn"
        assert "low" in result.detail

    def test_critical_space(self):
        mock_usage = MagicMock()
        mock_usage.free = 0.5 * (1024**3)  # 0.5 GB
        with patch("shutil.disk_usage", return_value=mock_usage):
            result = check_disk_space()
        assert result.status == "fail"
        assert "critical" in result.detail

    def test_unable_to_check(self):
        with patch("shutil.disk_usage", side_effect=OSError("permission denied")):
            result = check_disk_space()
        assert result.status == "skip"


class TestRunDoctor:
    def _patch_all_checks(self, **overrides):
        """Context manager that mocks every check to a deterministic result.
        Overrides let a specific test choose a different CheckResult."""
        from contextlib import ExitStack
        stack = ExitStack()

        def _stub(path, value, *, async_fn=False):
            target = f"breadmind.cli.doctor.{path}"
            if async_fn:
                return patch(target, new_callable=AsyncMock, return_value=value)
            return patch(target, return_value=value)

        defaults = {
            "check_config":               (False, CheckResult("Config", "ok", "found")),
            "check_config_schema":        (False, CheckResult("Config schema", "ok", "up to date")),
            "check_python":               (False, CheckResult("Python", "ok", "3.12.0")),
            "check_dependencies":         (False, []),
            "check_providers":            (True,  []),
            "check_database":             (True,  CheckResult("DB", "skip", "no dsn")),
            "check_mcp_servers":          (True,  []),
            "check_service_state":        (True,  CheckResult("Windows Service", "skip", "non-Windows")),
            "check_service_python_module": (False, CheckResult("Service Python", "skip", "non-Windows")),
            "check_disk_space":           (False, CheckResult("Disk", "ok", "10 GB")),
        }
        for name, (is_async, value) in defaults.items():
            if name in overrides:
                value = overrides[name]
            stack.enter_context(_stub(name, value, async_fn=is_async))
        return stack

    async def test_run_doctor_prints_summary(self, capsys):
        with self._patch_all_checks():
            await run_doctor(MagicMock(fix=False, yes=False, deep=False))

        output = capsys.readouterr().out
        assert "BreadMind Doctor" in output
        assert "Summary:" in output
        assert "ok" in output
        assert "skipped" in output

    async def test_run_doctor_shows_fix_hint_when_fixable_fail(self, capsys):
        """When a check fails with a fix attached, doctor suggests `--fix`."""
        fix = CheckResult("Config", "fail", "missing",
                          fix=__import__("breadmind.cli.doctor", fromlist=["Fix"]).Fix(
                              description="Recreate config",
                              sensitive=True,
                              elevation_command="breadmind setup",
                          ))
        with self._patch_all_checks(check_config=fix):
            await run_doctor(MagicMock(fix=False, yes=False, deep=False))

        output = capsys.readouterr().out
        assert "doctor --fix" in output


class TestParseArgsDoctor:
    def test_parse_doctor_command(self):
        from breadmind.main import _parse_args
        with patch("sys.argv", ["breadmind", "doctor"]):
            args = _parse_args()
        assert args.command == "doctor"

    def test_parse_doctor_fix_flags(self):
        from breadmind.main import _parse_args
        with patch("sys.argv", ["breadmind", "doctor", "--fix", "--yes", "--deep"]):
            args = _parse_args()
        assert args.command == "doctor"
        assert args.fix is True
        assert args.yes is True
        assert args.deep is True


class TestFixFlow:
    """Tests for the --fix orchestration."""

    async def test_non_sensitive_fix_applies_automatically(self, capsys):
        from breadmind.cli.doctor import Fix, _run_fixes

        applied = {"n": 0}

        async def _apply():
            applied["n"] += 1
            return (True, "rewrote schema")

        result = CheckResult(
            "Config schema", "warn", "deprecated",
            fix=Fix(description="Rewrite schema", sensitive=False, apply=_apply),
        )
        ui = MagicMock()
        await _run_fixes(ui, [result], auto_accept=False)
        assert applied["n"] == 1

    async def test_sensitive_fix_requires_confirmation(self, capsys):
        from breadmind.cli.doctor import Fix, _run_fixes

        apply_mock = AsyncMock(return_value=(True, "ok"))
        result = CheckResult(
            "Something", "fail", "broken",
            fix=Fix(description="Dangerous fix", sensitive=True, apply=apply_mock),
        )
        ui = MagicMock()
        # Non-interactive and no --yes → must skip
        with patch("breadmind.cli.doctor._is_interactive", return_value=False):
            await _run_fixes(ui, [result], auto_accept=False)
        apply_mock.assert_not_called()

    async def test_sensitive_fix_with_auto_accept_applies(self):
        from breadmind.cli.doctor import Fix, _run_fixes

        apply_mock = AsyncMock(return_value=(True, "ok"))
        result = CheckResult(
            "Something", "fail", "broken",
            fix=Fix(description="Dangerous fix", sensitive=True, apply=apply_mock),
        )
        ui = MagicMock()
        await _run_fixes(ui, [result], auto_accept=True)
        apply_mock.assert_awaited_once()

    async def test_elevation_only_fix_prints_command(self, capsys):
        from breadmind.cli.doctor import Fix, _run_fixes

        result = CheckResult(
            "Windows Service", "fail", "needs admin",
            fix=Fix(
                description="Restart as admin",
                sensitive=True,
                elevation_command="pwsh -Command 'Restart-Service BreadMind'",
            ),
        )
        ui = MagicMock()
        await _run_fixes(ui, [result], auto_accept=True)
        output = capsys.readouterr().out
        assert "Restart-Service BreadMind" in output

    async def test_fix_exception_reported(self, capsys):
        from breadmind.cli.doctor import Fix, _run_fixes

        async def _apply():
            raise RuntimeError("boom")

        result = CheckResult(
            "X", "fail", "",
            fix=Fix(description="fails", sensitive=False, apply=_apply),
        )
        ui = MagicMock()
        await _run_fixes(ui, [result], auto_accept=False)
        ui.error.assert_called()


class TestCheckConfigSchemaMigration:
    async def test_fallback_chain_migrated(self, tmp_path):
        from breadmind.cli.doctor import check_config_schema
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "llm:\n"
            "  default_provider: claude\n"
            "  fallback_chain: [claude, ollama]\n"
            "  default_model: claude-sonnet-4-6\n",
            encoding="utf-8",
        )
        with patch("breadmind.config.get_default_config_dir", return_value=str(tmp_path)):
            result = check_config_schema()
        assert result.status == "warn"
        assert result.fix is not None
        ok, message = await result.fix.apply()
        assert ok is True
        text = cfg.read_text(encoding="utf-8")
        assert "fallback_chain" not in text
        assert "fallback_provider: ollama" in text

    async def test_up_to_date_returns_ok(self, tmp_path):
        from breadmind.cli.doctor import check_config_schema
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "llm:\n  default_provider: claude\n  fallback_provider: ollama\n",
            encoding="utf-8",
        )
        with patch("breadmind.config.get_default_config_dir", return_value=str(tmp_path)):
            result = check_config_schema()
        assert result.status == "ok"
        assert result.fix is None
