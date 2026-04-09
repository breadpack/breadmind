"""macOS platform adapter using psutil and subprocess."""

from __future__ import annotations

import asyncio
import logging
import platform
import time
import webbrowser

from breadmind.companion.platform.base import PlatformAdapter

logger = logging.getLogger(__name__)


class MacOSAdapter(PlatformAdapter):
    """Companion platform adapter for macOS."""

    async def get_system_info(self) -> dict:
        import psutil
        boot_time = psutil.boot_time()
        return {
            "hostname": platform.node(),
            "os": "macOS",
            "os_version": platform.mac_ver()[0],
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
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            from pathlib import Path
            return Path(tmp_path).read_bytes()
        finally:
            import os
            os.unlink(tmp_path)

    async def get_clipboard(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "pbpaste",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")

    async def set_clipboard(self, text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text.encode("utf-8"))

    async def open_url(self, url: str) -> None:
        webbrowser.open(url)

    async def send_notification(self, title: str, body: str) -> None:
        script = f'display notification "{_escape_applescript(body)}" with title "{_escape_applescript(title)}"'
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def power_action(self, action: str) -> None:
        if action == "sleep":
            proc = await asyncio.create_subprocess_exec(
                "pmset", "sleepnow",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        elif action == "shutdown":
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e",
                'tell app "System Events" to shut down',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        elif action == "lock":
            proc = await asyncio.create_subprocess_exec(
                "pmset", "displaysleepnow",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        else:
            raise ValueError(f"Unknown power action: {action}")


def _escape_applescript(text: str) -> str:
    """Escape text for AppleScript string embedding."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
