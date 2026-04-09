"""Windows platform adapter using psutil, ctypes, and subprocess."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
import os
import platform
import subprocess
import time
from typing import Any

from breadmind.companion.platform.base import PlatformAdapter
from breadmind.companion.platform.windows_input import (
    send_key_combo,
    send_mouse_click,
    send_mouse_drag,
    send_mouse_scroll,
    send_unicode_char,
)

logger = logging.getLogger(__name__)

# Win32 window constants
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


class WindowsAdapter(PlatformAdapter):
    """Companion platform adapter for Windows."""

    async def get_system_info(self) -> dict:
        import psutil
        boot_time = psutil.boot_time()
        return {
            "hostname": platform.node(),
            "os": "Windows",
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "uptime_seconds": int(time.time() - boot_time),
        }

    async def get_cpu_info(self) -> dict:
        import psutil
        freq = psutil.cpu_freq()
        return {
            "count_physical": psutil.cpu_count(logical=False) or 0,
            "count_logical": psutil.cpu_count(logical=True) or 0,
            "percent": psutil.cpu_percent(interval=0.5),
            "freq_mhz": freq.current if freq else 0,
        }

    async def get_memory_info(self) -> dict:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        }

    async def get_disk_info(self) -> list[dict]:
        import psutil
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "mountpoint": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                })
            except PermissionError:
                continue
        return disks

    async def get_battery_info(self) -> dict | None:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return {
            "percent": battery.percent,
            "plugged": battery.power_plugged,
            "time_left_sec": battery.secsleft if battery.secsleft > 0 else None,
        }

    async def get_process_list(self, sort_by: str = "cpu") -> list[dict]:
        import psutil
        procs = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = proc.info
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_percent": info["cpu_percent"] or 0.0,
                    "memory_percent": round(info["memory_percent"] or 0.0, 2),
                    "status": info["status"],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
        procs.sort(key=lambda p: p[key], reverse=True)
        return procs[:50]

    async def kill_process(self, pid: int, force: bool = False) -> bool:
        import psutil
        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning("Failed to kill process %d: %s", pid, e)
            return False

    async def get_network_interfaces(self) -> list[dict]:
        import psutil
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        result = []
        for name, stat in stats.items():
            iface_addrs = []
            for addr in addrs.get(name, []):
                iface_addrs.append({
                    "family": str(addr.family),
                    "address": addr.address,
                    "netmask": addr.netmask,
                })
            result.append({
                "name": name,
                "is_up": stat.isup,
                "speed_mbps": stat.speed,
                "addresses": iface_addrs,
            })
        return result

    async def capture_screenshot(self) -> bytes:
        try:
            from mss import mss
            with mss() as sct:
                from mss.tools import to_png
                shot = sct.grab(sct.monitors[0])
                return to_png(shot.rgb, shot.size)
        except ImportError:
            pass
        try:
            from PIL import ImageGrab
            import io
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            pass
        raise RuntimeError("Screenshot requires mss or Pillow: pip install mss")

    async def get_clipboard(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", "Get-Clipboard",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip()

    async def set_clipboard(self, text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", f"Set-Clipboard -Value '{text}'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def open_url(self, url: str) -> None:
        os.startfile(url)

    async def send_notification(self, title: str, body: str) -> None:
        # Use PowerShell toast notification
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null; "
            "$template = '<toast><visual><binding template=\"ToastText02\">"
            f"<text id=\"1\">{_escape_xml(title)}</text>"
            f"<text id=\"2\">{_escape_xml(body)}</text>"
            "</binding></visual></toast>'; "
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$xml.LoadXml($template); "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('BreadMind').Show($toast)"
        )
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def power_action(self, action: str) -> None:
        if action == "lock":
            ctypes.windll.user32.LockWorkStation()
        elif action == "sleep":
            ctypes.windll.PowrProf.SetSuspendState(0, 1, 0)
        elif action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=True)
        else:
            raise ValueError(f"Unknown power action: {action}")

    # --- Window Management ---

    async def get_window_list(self) -> list[dict]:
        user32 = ctypes.windll.user32
        windows: list[dict] = []
        foreground_hwnd = user32.GetForegroundWindow()

        def _enum_callback(hwnd: int, _: Any) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            # Skip tool windows without app-window style
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                return True
            # Skip owned windows
            if user32.GetWindow(hwnd, GW_OWNER):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if not title:
                return True
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            # Get process name
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            app_name = ""
            try:
                import psutil
                app_name = psutil.Process(pid.value).name()
            except Exception:
                pass
            windows.append({
                "hwnd": hwnd,
                "title": title,
                "app_name": app_name,
                "x": rect.left,
                "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "is_focused": hwnd == foreground_hwnd,
            })
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
        enum_func = WNDENUMPROC(_enum_callback)
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: user32.EnumWindows(enum_func, 0)
        )
        return windows

    async def focus_window(self, window_id: int | str) -> bool:
        user32 = ctypes.windll.user32
        hwnd = int(window_id)
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception as e:
            logger.warning("Failed to focus window %s: %s", window_id, e)
            return False

    async def move_window(
        self,
        window_id: int | str,
        x: int,
        y: int,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        user32 = ctypes.windll.user32
        hwnd = int(window_id)
        try:
            if width is None or height is None:
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if width is None:
                    width = rect.right - rect.left
                if height is None:
                    height = rect.bottom - rect.top
            return bool(user32.MoveWindow(hwnd, x, y, width, height, True))
        except Exception as e:
            logger.warning("Failed to move window %s: %s", window_id, e)
            return False

    async def minimize_window(self, window_id: int | str) -> bool:
        try:
            ctypes.windll.user32.ShowWindow(int(window_id), SW_MINIMIZE)
            return True
        except Exception as e:
            logger.warning("Failed to minimize window %s: %s", window_id, e)
            return False

    async def maximize_window(self, window_id: int | str) -> bool:
        try:
            ctypes.windll.user32.ShowWindow(int(window_id), SW_MAXIMIZE)
            return True
        except Exception as e:
            logger.warning("Failed to maximize window %s: %s", window_id, e)
            return False

    async def close_window(self, window_id: int | str) -> bool:
        try:
            ctypes.windll.user32.SendMessageW(int(window_id), WM_CLOSE, 0, 0)
            return True
        except Exception as e:
            logger.warning("Failed to close window %s: %s", window_id, e)
            return False

    # --- Keyboard & Mouse ---

    async def type_text(self, text: str, interval: float = 0.0) -> None:
        for char in text:
            await send_unicode_char(char)
            if interval > 0:
                await asyncio.sleep(interval)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        await send_key_combo(key, modifiers)

    async def mouse_move(self, x: int, y: int) -> None:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ctypes.windll.user32.SetCursorPos(x, y)
        )

    async def mouse_click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        await self.mouse_move(x, y)
        await send_mouse_click(button, clicks)

    async def mouse_scroll(
        self, x: int, y: int, direction: str = "down", amount: int = 3
    ) -> None:
        await self.mouse_move(x, y)
        await send_mouse_scroll(direction, amount)

    async def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: str = "left", duration: float = 0.5,
    ) -> None:
        await send_mouse_drag(from_x, from_y, to_x, to_y, button, duration)

    async def capture_window_screenshot(self, window_id: int | str) -> bytes:
        user32 = ctypes.windll.user32
        hwnd = int(window_id)
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        x, y = rect.left, rect.top
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            raise RuntimeError(f"Invalid window dimensions for hwnd {hwnd}")
        try:
            from mss import mss
            from mss.tools import to_png
            with mss() as sct:
                monitor = {"left": x, "top": y, "width": w, "height": h}
                shot = sct.grab(monitor)
                return to_png(shot.rgb, shot.size)
        except ImportError:
            pass
        try:
            from PIL import ImageGrab
            import io
            img = ImageGrab.grab(bbox=(x, y, rect.right, rect.bottom))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            pass
        raise RuntimeError("Window screenshot requires mss or Pillow: pip install mss")


def _escape_xml(text: str) -> str:
    """Escape text for XML embedding."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )
