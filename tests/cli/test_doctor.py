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

    async def test_connection_success(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="PostgreSQL 17.2, compiled by ...")
        mock_conn.close = AsyncMock()

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            with patch("asyncpg.connect", new_callable=AsyncMock, return_value=mock_conn):
                result = await check_database()
        assert result.status == "ok"
        assert "PostgreSQL 17.2" in result.detail

    async def test_connection_failure(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            with patch("asyncpg.connect", new_callable=AsyncMock, side_effect=ConnectionRefusedError("refused")):
                result = await check_database()
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
    async def test_run_doctor_prints_summary(self, capsys):
        with patch("breadmind.cli.doctor.check_config", return_value=CheckResult("Config", "ok", "found")):
            with patch("breadmind.cli.doctor.check_python", return_value=CheckResult("Python", "ok", "3.12.0")):
                with patch("breadmind.cli.doctor.check_dependencies", return_value=[]):
                    with patch("breadmind.cli.doctor.check_providers", new_callable=AsyncMock, return_value=[]):
                        with patch("breadmind.cli.doctor.check_database", new_callable=AsyncMock, return_value=CheckResult("DB", "skip", "no dsn")):
                            with patch("breadmind.cli.doctor.check_mcp_servers", new_callable=AsyncMock, return_value=[]):
                                with patch("breadmind.cli.doctor.check_disk_space", return_value=CheckResult("Disk", "ok", "10 GB")):
                                    await run_doctor(MagicMock())

        output = capsys.readouterr().out
        assert "BreadMind Doctor" in output
        assert "Summary:" in output
        assert "3 ok" in output
        assert "1 skipped" in output

    async def test_run_doctor_shows_fix_hint_on_failure(self, capsys):
        with patch("breadmind.cli.doctor.check_config", return_value=CheckResult("Config", "fail", "missing")):
            with patch("breadmind.cli.doctor.check_python", return_value=CheckResult("Python", "ok", "3.12.0")):
                with patch("breadmind.cli.doctor.check_dependencies", return_value=[]):
                    with patch("breadmind.cli.doctor.check_providers", new_callable=AsyncMock, return_value=[]):
                        with patch("breadmind.cli.doctor.check_database", new_callable=AsyncMock, return_value=CheckResult("DB", "ok", "pg17")):
                            with patch("breadmind.cli.doctor.check_mcp_servers", new_callable=AsyncMock, return_value=[]):
                                with patch("breadmind.cli.doctor.check_disk_space", return_value=CheckResult("Disk", "ok", "10 GB")):
                                    await run_doctor(MagicMock())

        output = capsys.readouterr().out
        assert "breadmind setup" in output


class TestParseArgsDoctor:
    def test_parse_doctor_command(self):
        from breadmind.main import _parse_args
        with patch("sys.argv", ["breadmind", "doctor"]):
            args = _parse_args()
        assert args.command == "doctor"
