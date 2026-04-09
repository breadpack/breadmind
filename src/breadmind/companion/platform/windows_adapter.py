"""Windows platform adapter using psutil, ctypes, and subprocess."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import time
from typing import Any

from breadmind.companion.platform.base import PlatformAdapter

logger = logging.getLogger(__name__)


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
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif action == "sleep":
            import ctypes
            ctypes.windll.PowrProf.SetSuspendState(0, 1, 0)
        elif action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=True)
        else:
            raise ValueError(f"Unknown power action: {action}")


def _escape_xml(text: str) -> str:
    """Escape text for XML embedding."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )
