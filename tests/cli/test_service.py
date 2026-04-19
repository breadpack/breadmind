"""Tests for breadmind.cli.service."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from breadmind.cli import service


class TestParseScState:
    def test_running(self):
        out = """
SERVICE_NAME: BreadMind
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
"""
        assert service._parse_sc_state(out) == "RUNNING"

    def test_stopped(self):
        out = "SERVICE_NAME: BreadMind\n        STATE              : 1  STOPPED\n"
        assert service._parse_sc_state(out) == "STOPPED"

    def test_unknown(self):
        assert service._parse_sc_state("random text") == "UNKNOWN"


class TestIsAdmin:
    def test_non_nt_falls_back_to_geteuid(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "posix")
        # os.geteuid should be present on POSIX; if not, returns False safely.
        # Here we just verify the function doesn't raise.
        result = service.is_admin()
        assert isinstance(result, bool)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific behaviour")
class TestOnWindowsOnly:
    """Smoke checks against the real OS when running on Windows."""

    def test_nssm_path_returns_none_or_existing(self):
        path = service.nssm_path()
        if path is not None:
            assert path.exists()

    def test_default_config_dir_uses_appdata(self):
        cfg = service.default_config_dir()
        if os.environ.get("APPDATA"):
            assert "breadmind" in cfg.lower()


@pytest.mark.asyncio
class TestStatus:
    async def test_non_windows_returns_1(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "posix")
        rc = await service.status()
        assert rc == 1

    async def test_unregistered_returns_1(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        mock = AsyncMock(return_value=(1, ""))
        with patch.object(service, "_run", mock):
            rc = await service.status()
        assert rc == 1

    async def test_registered_returns_0(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        query_out = "SERVICE_NAME: BreadMind\n        STATE              : 1  STOPPED\n"
        qc_out = "        START_TYPE         : 2   AUTO_START\n"
        call_outputs = [(0, query_out), (0, qc_out)]
        async def fake_run(*args):
            return call_outputs.pop(0)
        with patch.object(service, "_run", fake_run):
            rc = await service.status()
        assert rc == 0


@pytest.mark.asyncio
class TestAdminGating:
    """All mutating actions must refuse to run without admin."""

    async def test_install_requires_admin(self, monkeypatch, capsys):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: False)
        rc = await service.install()
        assert rc == 1
        captured = capsys.readouterr().out
        assert "Administrator" in captured
        assert "breadmind service install" in captured

    async def test_start_requires_admin(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: False)
        rc = await service.start()
        assert rc == 1

    async def test_stop_requires_admin(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: False)
        rc = await service.stop()
        assert rc == 1

    async def test_restart_requires_admin(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: False)
        rc = await service.restart()
        assert rc == 1

    async def test_remove_requires_admin(self, monkeypatch):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: False)
        rc = await service.remove()
        assert rc == 1


@pytest.mark.asyncio
class TestDispatcher:
    async def test_unknown_action(self, capsys):
        args = SimpleNamespace(service_action=None)
        rc = await service.run_service_command(args)
        assert rc == 2
        assert "Usage" in capsys.readouterr().out

    async def test_status_dispatch(self, monkeypatch):
        called = AsyncMock(return_value=0)
        monkeypatch.setattr(service, "status", called)
        args = SimpleNamespace(service_action="status")
        rc = await service.run_service_command(args)
        assert rc == 0
        called.assert_awaited_once()

    async def test_install_dispatch_forwards_config_dir(self, monkeypatch):
        called = AsyncMock(return_value=0)
        monkeypatch.setattr(service, "install", called)
        args = SimpleNamespace(service_action="install", config_dir="C:\\foo")
        rc = await service.run_service_command(args)
        assert rc == 0
        called.assert_awaited_once_with("C:\\foo")


@pytest.mark.asyncio
class TestInstallHappyPath:
    async def test_install_runs_nssm_commands(self, monkeypatch, tmp_path):
        monkeypatch.setattr(service.os, "name", "nt")
        monkeypatch.setattr(service, "is_admin", lambda: True)
        fake_nssm = tmp_path / "nssm.exe"
        fake_nssm.write_text("")
        monkeypatch.setattr(service, "nssm_path", lambda: fake_nssm)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args):
            calls.append(args)
            return (0, "")

        monkeypatch.setattr(service, "_run", fake_run)
        rc = await service.install(config_dir=str(tmp_path))
        assert rc == 0
        # First call: remove (cleanup). Second: install. Then at least 6 `set` calls.
        verbs = [c[1] if len(c) > 1 else c[0] for c in calls]
        assert "install" in verbs
        assert verbs.count("set") >= 6
