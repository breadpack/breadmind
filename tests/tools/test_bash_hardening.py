"""Tests for bash hardening improvements in shell_exec."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.tools.builtin import (
    _truncate_head_tail,
    shell_exec,
)


def test_unc_path_blocked_on_windows():
    """UNC paths should be detected on Windows."""
    with patch("breadmind.tools.builtin.sys") as mock_sys:
        mock_sys.platform = "win32"
        # Re-evaluate with patched platform
        import breadmind.tools.builtin as mod
        orig = mod.sys
        mod.sys = mock_sys
        try:
            assert mod._contains_unc_path(r"type \\server\share\file.txt")
            assert mod._contains_unc_path(r"dir \\192.168.1.1\c$")
            assert not mod._contains_unc_path("echo hello")
            assert not mod._contains_unc_path(r"echo C:\Users\test")
        finally:
            mod.sys = orig


def test_unc_path_allowed_on_linux():
    """UNC path check should be skipped on Linux."""
    with patch("breadmind.tools.builtin.sys") as mock_sys:
        mock_sys.platform = "linux"
        import breadmind.tools.builtin as mod
        orig = mod.sys
        mod.sys = mock_sys
        try:
            assert not mod._contains_unc_path(r"cat \\server\share\file")
        finally:
            mod.sys = orig


def test_head_tail_truncation():
    """Large output should be truncated with head and tail preserved."""
    small = "x" * 100
    assert _truncate_head_tail(small) == small

    large = "A" * 30000 + "B" * 30000
    result = _truncate_head_tail(large, max_size=50000)
    assert "[...truncated" in result
    assert result.startswith("A" * 25000)
    assert result.endswith("B" * 25000)
    assert "10000 chars" in result  # 60000 - 50000 = 10000


async def test_partial_output_on_timeout():
    """Timeout should capture partial output."""
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()

    # First communicate() times out, second returns partial output
    call_count = 0

    async def mock_communicate():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()
        return (b"partial output here", b"")

    mock_proc.communicate = mock_communicate

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc), \
         patch("asyncio.wait_for", side_effect=[
             asyncio.TimeoutError(),
             (b"partial output here", b""),
         ]), \
         patch("breadmind.tools.builtin._is_command_allowed", return_value=(True, "")), \
         patch("breadmind.tools.builtin._contains_unc_path", return_value=False), \
         patch("breadmind.tools.builtin._has_shell_metacharacters", return_value=False), \
         patch("breadmind.tools.builtin.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = await shell_exec("long_command", timeout=1)
        assert "timed out" in result


async def test_background_execution():
    """Background execution should return a job ID immediately."""
    mock_proc = AsyncMock()
    mock_proc.pid = 12345

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc), \
         patch("breadmind.tools.builtin._is_command_allowed", return_value=(True, "")), \
         patch("breadmind.tools.builtin._contains_unc_path", return_value=False), \
         patch("breadmind.tools.builtin._has_shell_metacharacters", return_value=False), \
         patch("breadmind.tools.builtin.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = await shell_exec("sleep 100", run_in_background=True)
        assert "Background job started" in result
        assert "bg_" in result
