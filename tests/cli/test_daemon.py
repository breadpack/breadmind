"""Tests for breadmind.cli.daemon module."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.cli.daemon import (
    DaemonState,
    _cleanup_pid_files,
    _is_process_alive,
    daemon_status,
    get_pid_file,
    get_state_file,
    is_daemon_running,
    stop_daemon,
)


# ── get_pid_file / get_state_file ────────────────────────────────────────


class TestGetPidFile:
    def test_returns_path(self):
        p = get_pid_file()
        assert isinstance(p, Path)
        assert p.name == "daemon.pid"

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only")
    def test_windows_path(self):
        p = get_pid_file()
        # On Windows, should be under APPDATA/breadmind
        assert "breadmind" in str(p)

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only")
    def test_unix_path(self):
        p = get_pid_file()
        assert ".breadmind" in str(p)

    def test_state_file_matches_pid_file(self):
        pid_file = get_pid_file()
        state_file = get_state_file()
        assert state_file == pid_file.with_suffix(".json")


# ── is_daemon_running ─────────────────────────────────────────────────────


class TestIsDaemonRunning:
    def test_no_state_file_returns_none(self, tmp_path):
        with patch("breadmind.cli.daemon.get_state_file", return_value=tmp_path / "nonexistent.json"):
            assert is_daemon_running() is None

    def test_alive_process_returns_state(self, tmp_path):
        state = DaemonState(pid=12345, started_at="2026-01-01T00:00:00Z", host="0.0.0.0", port=8080)
        state_file = tmp_path / "daemon.json"
        pid_file = tmp_path / "daemon.pid"
        state_file.write_text(json.dumps(state.__dict__))
        pid_file.write_text("12345")

        with (
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon._is_process_alive", return_value=True),
        ):
            result = is_daemon_running()
            assert result is not None
            assert result.pid == 12345
            assert result.host == "0.0.0.0"
            assert result.port == 8080

    def test_dead_process_returns_none_and_cleans_up(self, tmp_path):
        state = DaemonState(pid=99999, started_at="2026-01-01T00:00:00Z", host="0.0.0.0", port=8080)
        state_file = tmp_path / "daemon.json"
        pid_file = tmp_path / "daemon.pid"
        state_file.write_text(json.dumps(state.__dict__))
        pid_file.write_text("99999")

        with (
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon._is_process_alive", return_value=False),
        ):
            result = is_daemon_running()
            assert result is None
            # Files should be cleaned up
            assert not state_file.exists()
            assert not pid_file.exists()

    def test_corrupt_state_file_returns_none(self, tmp_path):
        state_file = tmp_path / "daemon.json"
        state_file.write_text("not valid json")

        with patch("breadmind.cli.daemon.get_state_file", return_value=state_file):
            assert is_daemon_running() is None


# ── _cleanup_pid_files ────────────────────────────────────────────────────


class TestCleanupPidFiles:
    def test_removes_files(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        state_file = tmp_path / "daemon.json"
        pid_file.write_text("123")
        state_file.write_text("{}")

        with (
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
        ):
            _cleanup_pid_files()
            assert not pid_file.exists()
            assert not state_file.exists()

    def test_no_error_when_files_missing(self, tmp_path):
        pid_file = tmp_path / "daemon.pid"
        state_file = tmp_path / "daemon.json"

        with (
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
        ):
            # Should not raise
            _cleanup_pid_files()


# ── DaemonState serialization ─────────────────────────────────────────────


class TestDaemonState:
    def test_serialize_roundtrip(self):
        state = DaemonState(
            pid=42,
            started_at="2026-04-04T12:00:00+00:00",
            host="127.0.0.1",
            port=9090,
            status="running",
        )
        data = json.dumps(state.__dict__)
        restored = DaemonState(**json.loads(data))
        assert restored.pid == 42
        assert restored.host == "127.0.0.1"
        assert restored.port == 9090
        assert restored.status == "running"

    def test_default_status(self):
        state = DaemonState(pid=1, started_at="now", host="h", port=80)
        assert state.status == "running"


# ── _parse_args daemon subcommands ────────────────────────────────────────


class TestParseArgsDaemon:
    def test_daemon_start(self):
        from breadmind.main import _parse_args

        with patch("sys.argv", ["breadmind", "daemon", "start"]):
            args = _parse_args()
            assert args.command == "daemon"
            assert args.daemon_action == "start"
            assert args.host == "0.0.0.0"
            assert args.port == 8080

    def test_daemon_start_custom(self):
        from breadmind.main import _parse_args

        with patch("sys.argv", ["breadmind", "daemon", "start", "--host", "127.0.0.1", "--port", "3000"]):
            args = _parse_args()
            assert args.command == "daemon"
            assert args.host == "127.0.0.1"
            assert args.port == 3000

    def test_daemon_stop(self):
        from breadmind.main import _parse_args

        with patch("sys.argv", ["breadmind", "daemon", "stop"]):
            args = _parse_args()
            assert args.command == "daemon"
            assert args.daemon_action == "stop"

    def test_daemon_status(self):
        from breadmind.main import _parse_args

        with patch("sys.argv", ["breadmind", "daemon", "status"]):
            args = _parse_args()
            assert args.command == "daemon"
            assert args.daemon_action == "status"


# ── stop_daemon ───────────────────────────────────────────────────────────


class TestStopDaemon:
    async def test_no_daemon_running(self, capsys):
        with patch("breadmind.cli.daemon.is_daemon_running", return_value=None):
            await stop_daemon(SimpleNamespace())
        captured = capsys.readouterr()
        assert "No daemon running" in captured.out

    @pytest.mark.skipif(os.name == "nt", reason="Unix kill path")
    async def test_sends_sigterm_unix(self, tmp_path):
        state = DaemonState(pid=12345, started_at="now", host="h", port=80)
        pid_file = tmp_path / "daemon.pid"
        state_file = tmp_path / "daemon.json"
        pid_file.write_text("12345")
        state_file.write_text("{}")

        with (
            patch("breadmind.cli.daemon.is_daemon_running", return_value=state),
            patch("os.kill") as mock_kill,
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
        ):
            await stop_daemon(SimpleNamespace())
            mock_kill.assert_called_once_with(12345, __import__("signal").SIGTERM)

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only")
    async def test_calls_terminate_process_windows(self, tmp_path):
        state = DaemonState(pid=12345, started_at="now", host="h", port=80)
        pid_file = tmp_path / "daemon.pid"
        state_file = tmp_path / "daemon.json"
        pid_file.write_text("12345")
        state_file.write_text("{}")

        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = 123  # fake handle
        mock_kernel32.TerminateProcess.return_value = True

        with (
            patch("breadmind.cli.daemon.is_daemon_running", return_value=state),
            patch("ctypes.windll") as mock_windll,
            patch("breadmind.cli.daemon.get_pid_file", return_value=pid_file),
            patch("breadmind.cli.daemon.get_state_file", return_value=state_file),
        ):
            mock_windll.kernel32 = mock_kernel32
            await stop_daemon(SimpleNamespace())
            mock_kernel32.OpenProcess.assert_called_once_with(0x0001, False, 12345)
            mock_kernel32.TerminateProcess.assert_called_once()


# ── daemon_status ─────────────────────────────────────────────────────────


class TestDaemonStatus:
    async def test_not_running(self, capsys):
        with patch("breadmind.cli.daemon.is_daemon_running", return_value=None):
            await daemon_status(SimpleNamespace())
        captured = capsys.readouterr()
        assert "not running" in captured.out

    async def test_running(self, capsys):
        state = DaemonState(
            pid=42,
            started_at="2026-01-01T00:00:00Z",
            host="0.0.0.0",
            port=8080,
        )
        with patch("breadmind.cli.daemon.is_daemon_running", return_value=state):
            await daemon_status(SimpleNamespace())
        captured = capsys.readouterr()
        assert "running (PID 42)" in captured.out
        assert "http://0.0.0.0:8080" in captured.out
