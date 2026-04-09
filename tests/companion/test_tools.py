"""Tests for companion tool functions."""

from __future__ import annotations

import pytest

from breadmind.companion.security import PermissionManager
from breadmind.companion.tools import (
    companion_clipboard_read,
    companion_file_list,
    companion_file_read,
    companion_network_info,
    companion_notify,
    companion_open_url,
    companion_power,
    companion_process_kill,
    companion_process_list,
    companion_screenshot,
    companion_system_info,
    get_all_tools,
)
from tests.companion.conftest import MockPlatformAdapter


@pytest.fixture
def adapter():
    return MockPlatformAdapter()


@pytest.fixture
def perms():
    return PermissionManager(capabilities={
        "companion_system_info": True,
        "companion_process_list": True,
        "companion_process_kill": True,
        "companion_network_info": True,
        "companion_screenshot": True,
        "companion_clipboard_read": True,
        "companion_open_url": True,
        "companion_notify": True,
        "companion_power": True,
        "companion_file_read": True,
        "companion_file_list": True,
    })


async def test_system_info(adapter, perms):
    result = await companion_system_info(adapter, perms, {})
    assert "system" in result
    assert "cpu" in result
    assert "memory" in result
    assert "disks" in result


async def test_process_list(adapter, perms):
    result = await companion_process_list(adapter, perms, {"sort_by": "cpu"})
    assert result["count"] == 2
    assert result["processes"][0]["pid"] == 1


async def test_process_kill(adapter, perms):
    result = await companion_process_kill(adapter, perms, {"pid": 100})
    assert result["killed"] is True


async def test_process_kill_missing_pid(adapter, perms):
    result = await companion_process_kill(adapter, perms, {})
    assert "error" in result


async def test_network_info(adapter, perms):
    result = await companion_network_info(adapter, perms, {})
    assert len(result["interfaces"]) > 0


async def test_screenshot(adapter, perms):
    result = await companion_screenshot(adapter, perms, {})
    assert "image_base64" in result
    assert result["format"] == "png"


async def test_clipboard_read(adapter, perms):
    result = await companion_clipboard_read(adapter, perms, {})
    assert result["text"] == "clipboard content"


async def test_open_url(adapter, perms):
    result = await companion_open_url(adapter, perms, {"url": "https://example.com"})
    assert result["opened"] is True


async def test_open_url_missing(adapter, perms):
    result = await companion_open_url(adapter, perms, {})
    assert "error" in result


async def test_notify(adapter, perms):
    result = await companion_notify(adapter, perms, {"title": "Hi", "body": "Test"})
    assert result["sent"] is True


async def test_power_invalid_action(adapter, perms):
    result = await companion_power(adapter, perms, {"action": "explode"})
    assert "error" in result


async def test_file_read_sandbox(adapter, perms):
    """File read should deny paths outside allowed paths when configured."""
    perms_restricted = PermissionManager(
        capabilities={"companion_file_read": True},
        allowed_paths=["/tmp/allowed"],
    )
    result = await companion_file_read(adapter, perms_restricted, {"path": "/etc/passwd"})
    assert "error" in result
    assert "denied" in result["error"].lower()


async def test_file_list_missing_path(adapter, perms):
    result = await companion_file_list(adapter, perms, {})
    assert "error" in result


async def test_get_all_tools():
    tools = get_all_tools()
    assert "companion_system_info" in tools
    assert "companion_screenshot" in tools
    assert len(tools) == 12
