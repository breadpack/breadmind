"""Tests for SSH Sandbox Backend."""

from __future__ import annotations

import pytest

from breadmind.core.ssh_sandbox import SSHConfig, SSHResult, SSHSandbox


class TestSSHConfig:
    def test_defaults(self):
        cfg = SSHConfig(host="10.0.0.1")
        assert cfg.port == 22
        assert cfg.username == "sandbox"
        assert cfg.timeout == 30


class TestSSHSandbox:
    async def test_connect(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        assert not sandbox.connected
        result = await sandbox.connect()
        assert result is True
        assert sandbox.connected

    async def test_connect_empty_host_raises(self):
        sandbox = SSHSandbox(SSHConfig(host=""))
        with pytest.raises(ValueError, match="host is required"):
            await sandbox.connect()

    async def test_execute_without_connect_raises(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        with pytest.raises(RuntimeError, match="Not connected"):
            await sandbox.execute("ls")

    async def test_execute(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        await sandbox.connect()
        result = await sandbox.execute("ls -la")
        assert isinstance(result, SSHResult)
        assert result.returncode == 0
        assert result.host == "10.0.0.1"
        assert "ls -la" in result.stdout

    async def test_upload_requires_connection(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        with pytest.raises(RuntimeError, match="Not connected"):
            await sandbox.upload("/tmp/a", "/tmp/b")

    async def test_download_requires_connection(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        with pytest.raises(RuntimeError, match="Not connected"):
            await sandbox.download("/tmp/a", "/tmp/b")

    async def test_disconnect(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        await sandbox.connect()
        assert sandbox.connected
        await sandbox.disconnect()
        assert not sandbox.connected

    async def test_connect_idempotent(self):
        sandbox = SSHSandbox(SSHConfig(host="10.0.0.1"))
        await sandbox.connect()
        result = await sandbox.connect()
        assert result is True
