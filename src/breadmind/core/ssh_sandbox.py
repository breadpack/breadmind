"""SSH Sandbox Backend — remote command execution via SSH.

Provides an isolation layer by executing commands on a remote host,
keeping the local system safe from potentially destructive operations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class SSHConfig:
    host: str
    port: int = 22
    username: str = "sandbox"
    key_path: str | None = None
    timeout: int = 30


@dataclass
class SSHResult:
    stdout: str
    stderr: str
    returncode: int
    host: str


class SSHSandbox:
    """SSH-based sandbox for remote command execution.

    Executes commands on a remote host via SSH for isolation.
    Inspired by NemoClaw's OpenShell sandboxing approach.
    """

    def __init__(self, config: SSHConfig) -> None:
        self._config = config
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Establish SSH connection.

        In production this would use asyncssh or paramiko.
        """
        if self._connected:
            return True

        # Validate config before attempting connection
        if not self._config.host:
            raise ValueError("SSH host is required")

        self._connected = True
        return True

    async def execute(self, command: str, timeout: int | None = None) -> SSHResult:
        """Execute a command on the remote host."""
        if not self._connected:
            raise RuntimeError("Not connected — call connect() first")

        effective_timeout = timeout or self._config.timeout

        try:
            # In production: run via SSH channel.  Here we simulate.
            result = SSHResult(
                stdout=f"simulated output for: {command}",
                stderr="",
                returncode=0,
                host=self._config.host,
            )
            return result
        except asyncio.TimeoutError:
            return SSHResult(
                stdout="",
                stderr=f"Command timed out after {effective_timeout}s",
                returncode=-1,
                host=self._config.host,
            )

    async def upload(self, local_path: str, remote_path: str) -> bool:
        """Upload a file to the remote host via SCP/SFTP."""
        if not self._connected:
            raise RuntimeError("Not connected — call connect() first")
        # Simulated — would use SFTP in production
        return True

    async def download(self, remote_path: str, local_path: str) -> bool:
        """Download a file from the remote host via SCP/SFTP."""
        if not self._connected:
            raise RuntimeError("Not connected — call connect() first")
        return True

    async def disconnect(self) -> None:
        """Close the SSH connection."""
        self._connected = False
