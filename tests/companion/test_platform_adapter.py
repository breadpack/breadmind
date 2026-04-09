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
