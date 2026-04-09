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

    # --- Window Management ---

    @abstractmethod
    async def get_window_list(self) -> list[dict]:
        """Return list of visible windows: {hwnd/id, title, app_name, x, y, width, height, is_focused}."""

    @abstractmethod
    async def focus_window(self, window_id: int | str) -> bool:
        """Bring a window to the foreground."""

    @abstractmethod
    async def move_window(
        self,
        window_id: int | str,
        x: int,
        y: int,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        """Move/resize a window."""

    @abstractmethod
    async def minimize_window(self, window_id: int | str) -> bool:
        """Minimize a window."""

    @abstractmethod
    async def maximize_window(self, window_id: int | str) -> bool:
        """Maximize a window."""

    @abstractmethod
    async def close_window(self, window_id: int | str) -> bool:
        """Close a window."""

    # --- Keyboard & Mouse ---

    @abstractmethod
    async def type_text(self, text: str, interval: float = 0.0) -> None:
        """Type text as keyboard input at the current cursor position."""

    @abstractmethod
    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        """Press a key combo. key: 'enter', 'tab', 'a', 'f5', etc. modifiers: ['ctrl', 'alt', 'shift']."""

    @abstractmethod
    async def mouse_move(self, x: int, y: int) -> None:
        """Move mouse cursor to absolute screen coordinates."""

    @abstractmethod
    async def mouse_click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        """Click at coordinates. button: 'left', 'right', 'middle'."""

    @abstractmethod
    async def mouse_scroll(
        self, x: int, y: int, direction: str = "down", amount: int = 3
    ) -> None:
        """Scroll at coordinates. direction: 'up', 'down'."""

    @abstractmethod
    async def capture_window_screenshot(self, window_id: int | str) -> bytes:
        """Capture a specific window as PNG bytes."""
