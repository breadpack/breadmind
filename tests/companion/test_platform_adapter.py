"""Tests for platform adapter interface via MockPlatformAdapter."""

from __future__ import annotations

import pytest

from tests.companion.conftest import MockPlatformAdapter


@pytest.fixture
def adapter():
    return MockPlatformAdapter()


async def test_system_info(adapter):
    info = await adapter.get_system_info()
    assert "hostname" in info
    assert "os" in info
    assert "uptime_seconds" in info


async def test_cpu_info(adapter):
    cpu = await adapter.get_cpu_info()
    assert "count_logical" in cpu
    assert "percent" in cpu
    assert isinstance(cpu["percent"], (int, float))


async def test_memory_info(adapter):
    mem = await adapter.get_memory_info()
    assert mem["total"] > 0
    assert "percent" in mem


async def test_disk_info(adapter):
    disks = await adapter.get_disk_info()
    assert len(disks) > 0
    assert "mountpoint" in disks[0]
    assert "total" in disks[0]


async def test_battery_info(adapter):
    battery = await adapter.get_battery_info()
    assert battery is not None
    assert "percent" in battery
    assert "plugged" in battery


async def test_process_list(adapter):
    procs = await adapter.get_process_list()
    assert len(procs) > 0
    assert "pid" in procs[0]
    assert "name" in procs[0]


async def test_kill_process_success(adapter):
    result = await adapter.kill_process(100)
    assert result is True


async def test_kill_process_failure(adapter):
    result = await adapter.kill_process(99999)
    assert result is False


async def test_network_interfaces(adapter):
    ifaces = await adapter.get_network_interfaces()
    assert len(ifaces) > 0
    assert "name" in ifaces[0]
    assert "is_up" in ifaces[0]


async def test_capture_screenshot(adapter):
    data = await adapter.capture_screenshot()
    assert isinstance(data, bytes)
    assert len(data) > 0


async def test_clipboard(adapter):
    text = await adapter.get_clipboard()
    assert isinstance(text, str)
    await adapter.set_clipboard("test")


async def test_open_url(adapter):
    await adapter.open_url("https://example.com")


async def test_notification(adapter):
    await adapter.send_notification("Test", "Body")


async def test_power_action_valid(adapter):
    await adapter.power_action("lock")


async def test_power_action_invalid(adapter):
    with pytest.raises(ValueError):
        await adapter.power_action("explode")


# --- Window Management ---


async def test_window_list(adapter):
    windows = await adapter.get_window_list()
    assert len(windows) > 0
    win = windows[0]
    for key in ("title", "app_name", "x", "y", "width", "height", "is_focused"):
        assert key in win
    assert isinstance(win["is_focused"], bool)


async def test_focus_window(adapter):
    result = await adapter.focus_window(12345)
    assert result is True


async def test_focus_window_failure(adapter):
    result = await adapter.focus_window(99999)
    assert result is False


async def test_move_window(adapter):
    result = await adapter.move_window(12345, 100, 200, 800, 600)
    assert result is True


async def test_minimize_window(adapter):
    result = await adapter.minimize_window(12345)
    assert result is True


async def test_maximize_window(adapter):
    result = await adapter.maximize_window(12345)
    assert result is True


async def test_close_window(adapter):
    result = await adapter.close_window(12345)
    assert result is True


# --- Keyboard & Mouse ---


async def test_type_text(adapter):
    await adapter.type_text("hello world")


async def test_press_key(adapter):
    await adapter.press_key("enter", modifiers=["ctrl"])


async def test_mouse_move(adapter):
    await adapter.mouse_move(100, 200)


async def test_mouse_click(adapter):
    await adapter.mouse_click(100, 200, button="left", clicks=2)


async def test_mouse_scroll(adapter):
    await adapter.mouse_scroll(100, 200, direction="down", amount=3)


async def test_capture_window_screenshot(adapter):
    data = await adapter.capture_window_screenshot(12345)
    assert isinstance(data, bytes)
    assert len(data) > 0
