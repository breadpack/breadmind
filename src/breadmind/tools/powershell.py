"""Windows-native PowerShell execution tool.

Auto-detects ``pwsh.exe`` (PowerShell 7+) with fallback to
``powershell.exe`` (5.1).  Enabled via the
``BREADMIND_USE_POWERSHELL=1`` environment variable.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass


@dataclass
class PowerShellResult:
    stdout: str
    stderr: str
    returncode: int
    shell_version: str  # "pwsh7" or "powershell5"


class PowerShellExecutor:
    """Windows-native PowerShell execution.

    Auto-detects: ``pwsh.exe`` (PowerShell 7+) > ``powershell.exe`` (5.1).
    Enabled via ``BREADMIND_USE_POWERSHELL=1`` env var.
    """

    def __init__(self) -> None:
        self._shell_path: str | None = None
        self._shell_version: str = "unknown"
        self._detect_shell()

    @staticmethod
    def is_enabled() -> bool:
        return os.environ.get("BREADMIND_USE_POWERSHELL", "0") == "1"

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "win32" and (
            shutil.which("pwsh") is not None
            or shutil.which("powershell") is not None
        )

    @property
    def shell_path(self) -> str | None:
        return self._shell_path

    @property
    def shell_version(self) -> str:
        return self._shell_version

    def _detect_shell(self) -> None:
        """Find best available PowerShell.  Prefer pwsh (7+), fallback to powershell (5.1)."""
        pwsh = shutil.which("pwsh")
        if pwsh:
            self._shell_path = pwsh
            self._shell_version = "pwsh7"
            return

        ps = shutil.which("powershell")
        if ps:
            self._shell_path = ps
            self._shell_version = "powershell5"
            return

        self._shell_path = None
        self._shell_version = "unknown"

    async def execute(
        self,
        command: str,
        timeout_ms: int = 120_000,
        cwd: str | None = None,
    ) -> PowerShellResult:
        """Execute a PowerShell command string."""
        if self._shell_path is None:
            return PowerShellResult(
                stdout="",
                stderr="PowerShell is not available on this system.",
                returncode=-1,
                shell_version=self._shell_version,
            )

        args = [
            self._shell_path,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]

        timeout_s = timeout_ms / 1000.0

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return PowerShellResult(
                stdout="",
                stderr=f"Command timed out after {timeout_ms}ms",
                returncode=-2,
                shell_version=self._shell_version,
            )

        return PowerShellResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            returncode=proc.returncode or 0,
            shell_version=self._shell_version,
        )

    async def execute_script(
        self,
        script_path: str,
        timeout_ms: int = 120_000,
        cwd: str | None = None,
    ) -> PowerShellResult:
        """Execute a PowerShell script file (.ps1)."""
        if not script_path.endswith(".ps1"):
            return PowerShellResult(
                stdout="",
                stderr="Script path must end with .ps1",
                returncode=-1,
                shell_version=self._shell_version,
            )

        if not os.path.isfile(script_path):
            return PowerShellResult(
                stdout="",
                stderr=f"Script not found: {script_path}",
                returncode=-1,
                shell_version=self._shell_version,
            )

        command = f'& "{script_path}"'
        return await self.execute(command, timeout_ms=timeout_ms, cwd=cwd)
