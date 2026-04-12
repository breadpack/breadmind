"""Tests for PowerShell executor."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch


from breadmind.tools.powershell import PowerShellExecutor, PowerShellResult


class TestPowerShellResult:
    def test_dataclass_fields(self):
        r = PowerShellResult(stdout="out", stderr="err", returncode=0, shell_version="pwsh7")
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.returncode == 0
        assert r.shell_version == "pwsh7"


class TestIsEnabled:
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert PowerShellExecutor.is_enabled() is False

    def test_enabled_with_env(self):
        with patch.dict(os.environ, {"BREADMIND_USE_POWERSHELL": "1"}):
            assert PowerShellExecutor.is_enabled() is True

    def test_disabled_with_zero(self):
        with patch.dict(os.environ, {"BREADMIND_USE_POWERSHELL": "0"}):
            assert PowerShellExecutor.is_enabled() is False


class TestIsAvailable:
    @patch("breadmind.tools.powershell.sys")
    @patch("breadmind.tools.powershell.shutil.which")
    def test_available_on_windows_with_pwsh(self, mock_which, mock_sys):
        mock_sys.platform = "win32"
        mock_which.side_effect = lambda x: "/usr/bin/pwsh" if x == "pwsh" else None
        assert PowerShellExecutor.is_available() is True

    @patch("breadmind.tools.powershell.sys")
    @patch("breadmind.tools.powershell.shutil.which")
    def test_not_available_on_linux(self, mock_which, mock_sys):
        mock_sys.platform = "linux"
        assert PowerShellExecutor.is_available() is False


class TestDetectShell:
    @patch("breadmind.tools.powershell.shutil.which")
    def test_prefers_pwsh(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/pwsh" if x == "pwsh" else "/usr/bin/powershell"
        executor = PowerShellExecutor()
        assert executor.shell_version == "pwsh7"
        assert executor.shell_path == "/usr/bin/pwsh"

    @patch("breadmind.tools.powershell.shutil.which")
    def test_fallback_to_powershell(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/powershell" if x == "powershell" else None
        executor = PowerShellExecutor()
        assert executor.shell_version == "powershell5"

    @patch("breadmind.tools.powershell.shutil.which", return_value=None)
    def test_no_shell(self, mock_which):
        executor = PowerShellExecutor()
        assert executor.shell_path is None
        assert executor.shell_version == "unknown"


class TestExecute:
    @patch("breadmind.tools.powershell.shutil.which", return_value=None)
    async def test_execute_no_shell(self, mock_which):
        executor = PowerShellExecutor()
        result = await executor.execute("Get-Date")
        assert result.returncode == -1
        assert "not available" in result.stderr

    @patch("breadmind.tools.powershell.shutil.which")
    @patch("breadmind.tools.powershell.asyncio.create_subprocess_exec")
    async def test_execute_success(self, mock_create, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/pwsh" if x == "pwsh" else None

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0
        mock_create.return_value = mock_proc

        executor = PowerShellExecutor()
        result = await executor.execute("Write-Output hello")
        assert result.stdout == "hello\n"
        assert result.returncode == 0

    @patch("breadmind.tools.powershell.shutil.which")
    async def test_execute_script_bad_extension(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/pwsh" if x == "pwsh" else None
        executor = PowerShellExecutor()
        result = await executor.execute_script("script.sh")
        assert result.returncode == -1
        assert ".ps1" in result.stderr

    @patch("breadmind.tools.powershell.shutil.which")
    async def test_execute_script_not_found(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/pwsh" if x == "pwsh" else None
        executor = PowerShellExecutor()
        result = await executor.execute_script("/nonexistent/script.ps1")
        assert result.returncode == -1
        assert "not found" in result.stderr
