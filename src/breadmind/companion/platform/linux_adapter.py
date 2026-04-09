"""Linux platform adapter using psutil and subprocess."""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import time
import webbrowser

from breadmind.companion.platform.base import PlatformAdapter

logger = logging.getLogger(__name__)


class LinuxAdapter(PlatformAdapter):
    """Companion platform adapter for Linux (X11/Wayland)."""

    async def get_system_info(self) -> dict:
        import psutil
        boot_time = psutil.boot_time()
        return {
            "hostname": platform.node(),
            "os": "Linux",
            "os_version": platform.release(),
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
        import os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # Try Wayland first (grim), then X11 (scrot), then mss
            if shutil.which("grim"):
                cmd = ["grim", tmp_path]
            elif shutil.which("scrot"):
                cmd = ["scrot", tmp_path]
            else:
                # Fallback to mss
                try:
                    from mss import mss
                    from mss.tools import to_png
                    with mss() as sct:
                        shot = sct.grab(sct.monitors[0])
                        return to_png(shot.rgb, shot.size)
                except ImportError:
                    raise RuntimeError(
                        "Screenshot requires grim (Wayland), scrot (X11), or mss"
                    )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            from pathlib import Path
            return Path(tmp_path).read_bytes()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def get_clipboard(self) -> str:
        # Try wl-paste (Wayland), then xclip (X11), then xsel
        for cmd in [
            ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ]:
            if shutil.which(cmd[0]):
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    return stdout.decode("utf-8", errors="replace")
        raise RuntimeError("No clipboard tool found (install wl-paste, xclip, or xsel)")

    async def set_clipboard(self, text: str) -> None:
        for cmd in [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]:
            if shutil.which(cmd[0]):
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate(input=text.encode("utf-8"))
                return
        raise RuntimeError("No clipboard tool found (install wl-copy, xclip, or xsel)")

    async def open_url(self, url: str) -> None:
        webbrowser.open(url)

    async def send_notification(self, title: str, body: str) -> None:
        if shutil.which("notify-send"):
            proc = await asyncio.create_subprocess_exec(
                "notify-send", title, body,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        else:
            logger.warning("notify-send not found, notification skipped")

    async def power_action(self, action: str) -> None:
        if action == "sleep":
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "suspend",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        elif action == "shutdown":
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "poweroff",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        elif action == "lock":
            proc = await asyncio.create_subprocess_exec(
                "loginctl", "lock-session",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        else:
            raise ValueError(f"Unknown power action: {action}")
