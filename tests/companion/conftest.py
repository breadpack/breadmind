"""Shared fixtures for companion tests."""

from __future__ import annotations


import pytest

from breadmind.companion.platform.base import PlatformAdapter


class MockPlatformAdapter(PlatformAdapter):
    """Mock adapter for testing — returns predictable data."""

    async def get_system_info(self) -> dict:
        return {
            "hostname": "test-host",
            "os": "TestOS",
            "os_version": "1.0",
            "architecture": "x86_64",
            "processor": "TestCPU",
            "uptime_seconds": 3600,
        }

    async def get_cpu_info(self) -> dict:
        return {
            "count_physical": 4,
            "count_logical": 8,
            "percent": 25.0,
            "freq_mhz": 3600,
        }

    async def get_memory_info(self) -> dict:
        return {
            "total": 16_000_000_000,
            "available": 8_000_000_000,
            "used": 8_000_000_000,
            "percent": 50.0,
        }

    async def get_disk_info(self) -> list[dict]:
        return [{
            "mountpoint": "/",
            "device": "/dev/sda1",
            "fstype": "ext4",
            "total": 500_000_000_000,
            "used": 200_000_000_000,
            "free": 300_000_000_000,
            "percent": 40.0,
        }]

    async def get_battery_info(self) -> dict | None:
        return {"percent": 85.0, "plugged": True, "time_left_sec": None}

    async def get_process_list(self, sort_by: str = "cpu") -> list[dict]:
        return [
            {"pid": 1, "name": "init", "cpu_percent": 0.1, "memory_percent": 0.5, "status": "running"},
            {"pid": 100, "name": "python", "cpu_percent": 15.0, "memory_percent": 3.2, "status": "running"},
        ]

    async def kill_process(self, pid: int, force: bool = False) -> bool:
        return pid != 99999  # Simulate failure for pid 99999

    async def get_network_interfaces(self) -> list[dict]:
        return [{
            "name": "eth0",
            "is_up": True,
            "speed_mbps": 1000,
            "addresses": [{"family": "AF_INET", "address": "192.168.1.10", "netmask": "255.255.255.0"}],
        }]

    async def capture_screenshot(self) -> bytes:
        # Return minimal valid PNG bytes (1x1 pixel)
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    async def get_clipboard(self) -> str:
        return "clipboard content"

    async def set_clipboard(self, text: str) -> None:
        pass

    async def open_url(self, url: str) -> None:
        pass

    async def send_notification(self, title: str, body: str) -> None:
        pass

    async def power_action(self, action: str) -> None:
        if action not in ("sleep", "shutdown", "lock"):
            raise ValueError(f"Unknown power action: {action}")

    # --- Window Management ---

    async def get_window_list(self) -> list[dict]:
        return [
            {
                "hwnd": 12345,
                "title": "Test Window",
                "app_name": "test.exe",
                "x": 0, "y": 0, "width": 800, "height": 600,
                "is_focused": True,
            },
            {
                "hwnd": 67890,
                "title": "Background Window",
                "app_name": "bg.exe",
                "x": 100, "y": 100, "width": 640, "height": 480,
                "is_focused": False,
            },
        ]

    async def focus_window(self, window_id: int | str) -> bool:
        return int(window_id) != 99999

    async def move_window(
        self,
        window_id: int | str,
        x: int,
        y: int,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        return int(window_id) != 99999

    async def minimize_window(self, window_id: int | str) -> bool:
        return int(window_id) != 99999

    async def maximize_window(self, window_id: int | str) -> bool:
        return int(window_id) != 99999

    async def close_window(self, window_id: int | str) -> bool:
        return int(window_id) != 99999

    # --- Keyboard & Mouse ---

    async def type_text(self, text: str, interval: float = 0.0) -> None:
        pass

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        pass

    async def mouse_move(self, x: int, y: int) -> None:
        pass

    async def mouse_click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        pass

    async def mouse_scroll(
        self, x: int, y: int, direction: str = "down", amount: int = 3
    ) -> None:
        pass

    async def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: str = "left", duration: float = 0.5,
    ) -> None:
        pass

    async def capture_window_screenshot(self, window_id: int | str) -> bytes:
        # Return minimal valid PNG bytes (1x1 pixel)
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )


@pytest.fixture
def mock_adapter() -> MockPlatformAdapter:
    return MockPlatformAdapter()
