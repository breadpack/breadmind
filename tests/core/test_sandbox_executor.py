"""Tests for SandboxExecutor — filesystem/Docker isolation wrapper."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.core.sandbox_executor import (
    DEFAULT_BLOCKED_PATHS,
    SandboxConfig,
    SandboxExecutor,
    SandboxMode,
    SandboxResult,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_executor(**overrides) -> SandboxExecutor:
    cfg = SandboxConfig(**overrides)
    return SandboxExecutor(config=cfg)


def _fake_process(stdout: bytes = b"ok\n", returncode: int = 0):
    """Create a mock process returned by create_subprocess_shell."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# ── Tests ────────────────────────────────────────────────────────────


def test_default_config_is_filesystem():
    executor = SandboxExecutor()
    assert executor._config.mode == SandboxMode.FILESYSTEM


def test_blocked_paths_configurable():
    custom_blocked = ["/secret/dir", "/other/path"]
    executor = _make_executor(blocked_paths=custom_blocked)
    assert executor._config.blocked_paths == custom_blocked


async def test_filesystem_mode_blocks_sensitive_paths():
    executor = _make_executor(mode=SandboxMode.FILESYSTEM)
    result = await executor.execute("cat /etc/shadow")
    assert not result.success
    assert "restricted path" in result.output.lower() or "blocked" in result.output.lower()
    assert result.mode_used == SandboxMode.FILESYSTEM


async def test_filesystem_mode_allows_safe_commands():
    executor = _make_executor(mode=SandboxMode.FILESYSTEM)
    proc = _fake_process(b"hello\n", 0)

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        result = await executor.execute("echo hello")

    assert result.success
    assert result.output == "hello\n"
    assert result.mode_used == SandboxMode.FILESYSTEM


async def test_validate_path_detects_symlink_escape():
    """A symlink that resolves outside allowed paths must be rejected."""
    executor = _make_executor(
        mode=SandboxMode.FILESYSTEM,
        allowed_paths=["/safe/area"],
    )

    # os.path.realpath will resolve the symlink to the actual target
    with patch("os.path.realpath", side_effect=lambda p: {
        "/safe/area": "/safe/area",
        "/safe/area/link": "/etc/shadow",
    }.get(p, p)):
        assert not executor.validate_path("/safe/area/link")


async def test_env_sanitization_removes_secrets():
    fake_env = {
        "HOME": "/home/user",
        "PATH": "/usr/bin",
        "AWS_SECRET_KEY": "s3cr3t",
        "OPENAI_API_KEY": "sk-xxx",
        "DATABASE_PASSWORD": "pass123",
        "MY_TOKEN": "tok",
        "NORMAL_VAR": "keep",
    }

    with patch.dict(os.environ, fake_env, clear=True):
        sanitized = SandboxExecutor._sanitized_env()

    assert "HOME" in sanitized
    assert "PATH" in sanitized
    assert "NORMAL_VAR" in sanitized
    assert "AWS_SECRET_KEY" not in sanitized
    assert "OPENAI_API_KEY" not in sanitized
    assert "DATABASE_PASSWORD" not in sanitized
    assert "MY_TOKEN" not in sanitized


async def test_docker_mode_builds_correct_command():
    executor = _make_executor(
        mode=SandboxMode.DOCKER,
        docker_image="alpine:latest",
        max_memory_mb=256,
        network_allowed=False,
        allowed_paths=["/data"],
    )
    proc = _fake_process(b"done\n", 0)

    with patch("asyncio.create_subprocess_shell", return_value=proc) as mock_shell:
        result = await executor.execute("ls /data", workdir="/data")

    assert result.success
    assert result.mode_used == SandboxMode.DOCKER

    cmd_str = mock_shell.call_args[0][0]
    assert "--rm" in cmd_str
    assert "--read-only" in cmd_str
    assert "--memory=256m" in cmd_str
    assert "--network=none" in cmd_str
    assert "alpine:latest" in cmd_str
    assert "/data:/data:ro" in cmd_str
    assert "-w /data" in cmd_str


async def test_timeout_enforcement():
    executor = _make_executor(mode=SandboxMode.FILESYSTEM, timeout_seconds=1)

    proc = AsyncMock()
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        result = await executor.execute("sleep 999")

    assert not result.success
    assert "timed out" in result.output.lower()
