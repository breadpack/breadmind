"""Abstract base class for platform-specific operations."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """Interface for platform-specific companion operations.

    Each method is async to allow non-blocking subprocess calls on
    platforms that require external commands.
    """

    @abstractmethod
    async def get_system_info(self) -> dict:
        """Return OS, hostname, architecture, uptime, etc."""

    @abstractmethod
    async def get_cpu_info(self) -> dict:
        """Return cpu_count, percent, freq_mhz, etc."""

    @abstractmethod
    async def get_memory_info(self) -> dict:
        """Return total, available, used, percent."""

    @abstractmethod
    async def get_disk_info(self) -> list[dict]:
        """Return list of {mountpoint, total, used, free, percent}."""

    @abstractmethod
    async def get_battery_info(self) -> dict | None:
        """Return {percent, plugged, time_left_sec} or None if no battery."""

    @abstractmethod
    async def get_process_list(self, sort_by: str = "cpu") -> list[dict]:
        """Return top processes sorted by cpu or memory."""

    @abstractmethod
    async def kill_process(self, pid: int, force: bool = False) -> bool:
        """Kill a process by PID. Returns True on success."""

    @abstractmethod
    async def get_network_interfaces(self) -> list[dict]:
        """Return list of {name, addresses, mac, is_up}."""

    @abstractmethod
    async def capture_screenshot(self) -> bytes:
        """Capture current screen and return PNG bytes."""

    @abstractmethod
    async def get_clipboard(self) -> str:
        """Read clipboard text content."""

    @abstractmethod
    async def set_clipboard(self, text: str) -> None:
        """Write text to clipboard."""

    @abstractmethod
    async def open_url(self, url: str) -> None:
        """Open a URL in the default browser."""

    @abstractmethod
    async def send_notification(self, title: str, body: str) -> None:
        """Show a desktop notification."""

    @abstractmethod
    async def power_action(self, action: str) -> None:
        """Execute power action: sleep, shutdown, lock."""
