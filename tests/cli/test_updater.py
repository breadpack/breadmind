"""Tests for breadmind.cli.updater."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.cli import updater


class TestIsNewer:
    def test_strictly_newer(self):
        assert updater.is_newer("0.3.2", "0.3.1") is True

    def test_equal(self):
        assert updater.is_newer("0.3.1", "0.3.1") is False

    def test_older(self):
        assert updater.is_newer("0.3.0", "0.3.1") is False

    def test_prerelease_is_older_than_stable(self):
        """PEP 440: 0.4.0rc1 < 0.4.0."""
        assert updater.is_newer("0.4.0rc1", "0.4.0") is False
        assert updater.is_newer("0.4.0", "0.4.0rc1") is True

    def test_non_version_fallback(self):
        # packaging.Version raises on these; fallback is lexicographic.
        # Either branch is acceptable as long as it doesn't crash.
        assert updater.is_newer("not-a-version", "not-a-version") is False


class TestDetectInstallMode:
    def _mock_distribution(self, direct_url_json: str | None):
        dist = MagicMock()
        dist.read_text.return_value = direct_url_json
        return dist

    def test_editable_install(self):
        if os.name == "nt":
            url = "file:///D:/Projects/breadmind"
        else:
            url = "file:///home/user/breadmind"
        payload = json.dumps({"url": url, "dir_info": {"editable": True}})
        dist = self._mock_distribution(payload)
        with patch("importlib.metadata.distribution", return_value=dist):
            info = updater.detect_install_mode()
        assert info.mode == "editable"
        assert info.editable_path is not None
        # Path resolution is platform-specific; just verify basename.
        assert "breadmind" in str(info.editable_path).lower()

    def test_git_install(self):
        payload = json.dumps({
            "url": "https://github.com/breadpack/breadmind.git",
            "vcs_info": {"vcs": "git", "commit_id": "abc123"},
        })
        dist = self._mock_distribution(payload)
        with patch("importlib.metadata.distribution", return_value=dist):
            info = updater.detect_install_mode()
        assert info.mode == "git"
        assert info.git_url == "https://github.com/breadpack/breadmind.git"

    def test_no_direct_url_is_pypi(self):
        dist = self._mock_distribution(None)
        with patch("importlib.metadata.distribution", return_value=dist):
            info = updater.detect_install_mode()
        assert info.mode == "pypi"

    def test_invalid_json_is_unknown(self):
        dist = self._mock_distribution("not-json{")
        with patch("importlib.metadata.distribution", return_value=dist):
            info = updater.detect_install_mode()
        assert info.mode == "unknown"

    def test_missing_distribution_is_pypi(self):
        """When the package isn't installed at all, we default to PyPI."""
        with patch("importlib.metadata.distribution", side_effect=Exception("missing")):
            info = updater.detect_install_mode()
        assert info.mode == "pypi"


@pytest.mark.asyncio
class TestFetchLatestVersion:
    async def test_success_strips_v_prefix(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"tag_name": "v0.5.2"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            result = await updater.fetch_latest_version()
        assert result == "0.5.2"

    async def test_non_200_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            result = await updater.fetch_latest_version()
        assert result is None

    async def test_network_error_returns_none(self):
        with patch("aiohttp.ClientSession.get", side_effect=Exception("no network")):
            result = await updater.fetch_latest_version()
        assert result is None

    async def test_empty_tag_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"tag_name": ""})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession.get", return_value=mock_resp):
            result = await updater.fetch_latest_version()
        assert result is None


@pytest.mark.asyncio
class TestRunUpdateOrchestrator:
    async def test_already_up_to_date_short_circuits(self):
        with patch.object(updater, "get_current_version", return_value="0.3.1"), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.3.1")):
            rc = await updater.run_update()
        assert rc == 0

    async def test_cannot_reach_github(self):
        with patch.object(updater, "get_current_version", return_value="0.3.1"), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value=None)):
            rc = await updater.run_update()
        assert rc == 1

    async def test_check_only_does_not_install(self):
        install = AsyncMock()
        with patch.object(updater, "get_current_version", return_value="0.3.0"), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.4.0")), \
             patch.object(updater, "update_editable", install), \
             patch.object(updater, "update_from_git", install), \
             patch.object(updater, "update_from_pypi", install), \
             patch.object(updater, "restart_service_if_running", AsyncMock()):
            rc = await updater.run_update(check_only=True)
        assert rc == 0
        install.assert_not_called()

    async def test_editable_path_is_used(self, tmp_path: Path):
        info = updater.InstallInfo(mode="editable", editable_path=tmp_path)
        editable_mock = AsyncMock(return_value=True)
        with patch.object(updater, "get_current_version", side_effect=["0.3.0", "0.4.0"]), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.4.0")), \
             patch.object(updater, "detect_install_mode", return_value=info), \
             patch.object(updater, "update_editable", editable_mock), \
             patch.object(updater, "update_from_git", AsyncMock(return_value=False)), \
             patch.object(updater, "update_from_pypi", AsyncMock(return_value=False)), \
             patch.object(updater, "restart_service_if_running", AsyncMock()):
            rc = await updater.run_update()
        assert rc == 0
        editable_mock.assert_awaited_once_with(tmp_path)

    async def test_pypi_mode_uses_pypi_upgrade(self):
        info = updater.InstallInfo(mode="pypi")
        pypi_mock = AsyncMock(return_value=True)
        with patch.object(updater, "get_current_version", side_effect=["0.3.0", "0.4.0"]), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.4.0")), \
             patch.object(updater, "detect_install_mode", return_value=info), \
             patch.object(updater, "update_editable", AsyncMock(return_value=False)), \
             patch.object(updater, "update_from_git", AsyncMock(return_value=False)), \
             patch.object(updater, "update_from_pypi", pypi_mock), \
             patch.object(updater, "restart_service_if_running", AsyncMock()):
            rc = await updater.run_update()
        assert rc == 0
        pypi_mock.assert_awaited_once()

    async def test_no_restart_flag_skips_service_restart(self):
        info = updater.InstallInfo(mode="pypi")
        restart_mock = AsyncMock()
        with patch.object(updater, "get_current_version", side_effect=["0.3.0", "0.4.0"]), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.4.0")), \
             patch.object(updater, "detect_install_mode", return_value=info), \
             patch.object(updater, "update_from_pypi", AsyncMock(return_value=True)), \
             patch.object(updater, "restart_service_if_running", restart_mock):
            rc = await updater.run_update(no_restart=True)
        assert rc == 0
        restart_mock.assert_not_called()

    async def test_update_failure_returns_nonzero(self):
        info = updater.InstallInfo(mode="pypi")
        with patch.object(updater, "get_current_version", return_value="0.3.0"), \
             patch.object(updater, "fetch_latest_version", AsyncMock(return_value="0.4.0")), \
             patch.object(updater, "detect_install_mode", return_value=info), \
             patch.object(updater, "update_from_pypi", AsyncMock(return_value=False)), \
             patch.object(updater, "restart_service_if_running", AsyncMock()):
            rc = await updater.run_update()
        assert rc == 2
