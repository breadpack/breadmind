"""Tests for companion tool functions."""

from __future__ import annotations

import pytest

from breadmind.companion.security import PermissionManager
from breadmind.companion.tools import (
    companion_clipboard_read,
    companion_file_list,
    companion_file_read,
    companion_mouse_click,
    companion_mouse_move,
    companion_mouse_scroll,
    companion_network_info,
    companion_notify,
    companion_open_url,
    companion_power,
    companion_press_key,
    companion_process_kill,
    companion_process_list,
    companion_screenshot,
    companion_system_info,
    companion_type_text,
    companion_window_close,
    companion_window_focus,
    companion_window_list,
    companion_window_maximize,
    companion_window_minimize,
    companion_window_move,
    companion_window_screenshot,
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
        "window_mgmt": True,
        "input_control": True,
        "companion_window_close": True,
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
    assert "companion_window_list" in tools
    assert "companion_type_text" in tools
    assert "companion_mouse_click" in tools
    assert len(tools) == 24


# --- Window Management Tools ---


async def test_window_list(adapter, perms):
    result = await companion_window_list(adapter, perms, {})
    assert result["count"] == 2
    assert result["windows"][0]["title"] == "Test Window"


async def test_window_focus(adapter, perms):
    result = await companion_window_focus(adapter, perms, {"window_id": 12345})
    assert result["focused"] is True


async def test_window_focus_missing_id(adapter, perms):
    result = await companion_window_focus(adapter, perms, {})
    assert "error" in result


async def test_window_move(adapter, perms):
    result = await companion_window_move(adapter, perms, {"window_id": 12345, "x": 100, "y": 200})
    assert result["moved"] is True


async def test_window_move_missing_coords(adapter, perms):
    result = await companion_window_move(adapter, perms, {"window_id": 12345})
    assert "error" in result


async def test_window_minimize(adapter, perms):
    result = await companion_window_minimize(adapter, perms, {"window_id": 12345})
    assert result["minimized"] is True


async def test_window_maximize(adapter, perms):
    result = await companion_window_maximize(adapter, perms, {"window_id": 12345})
    assert result["maximized"] is True


async def test_window_close(adapter, perms):
    result = await companion_window_close(adapter, perms, {"window_id": 12345})
    assert result["closed"] is True


async def test_window_screenshot(adapter, perms):
    result = await companion_window_screenshot(adapter, perms, {"window_id": 12345})
    assert "image_base64" in result
    assert result["format"] == "png"


# --- Input Control Tools ---


async def test_type_text(adapter, perms):
    result = await companion_type_text(adapter, perms, {"text": "hello"})
    assert result["typed"] is True
    assert result["length"] == 5


async def test_type_text_missing(adapter, perms):
    result = await companion_type_text(adapter, perms, {})
    assert "error" in result


async def test_press_key(adapter, perms):
    result = await companion_press_key(adapter, perms, {"key": "enter", "modifiers": ["ctrl"]})
    assert result["pressed"] is True


async def test_press_key_missing(adapter, perms):
    result = await companion_press_key(adapter, perms, {})
    assert "error" in result


async def test_mouse_move(adapter, perms):
    result = await companion_mouse_move(adapter, perms, {"x": 100, "y": 200})
    assert result["moved"] is True


async def test_mouse_click(adapter, perms):
    result = await companion_mouse_click(adapter, perms, {"x": 100, "y": 200, "button": "right"})
    assert result["clicked"] is True
    assert result["button"] == "right"


async def test_mouse_scroll(adapter, perms):
    result = await companion_mouse_scroll(adapter, perms, {"x": 100, "y": 200, "direction": "up"})
    assert result["scrolled"] is True
    assert result["direction"] == "up"


# --- Permission Denied for Input Control ---


async def test_input_control_denied_by_default():
    """Input control tools should be denied when input_control capability is off."""
    pm = PermissionManager()
    assert pm.is_allowed("companion_type_text") is False
    assert pm.is_allowed("companion_press_key") is False
    assert pm.is_allowed("companion_mouse_click") is False
    assert pm.is_allowed("companion_mouse_move") is False
    assert pm.is_allowed("companion_mouse_scroll") is False
