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

    # --- Window Management ---

    async def _run_cmd(self, *args: str) -> str:
        """Run a command and return stdout, raising on failure."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Command {args[0]} failed: {err}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def get_window_list(self) -> list[dict]:
        if not shutil.which("xdotool"):
            raise RuntimeError("Window listing requires xdotool: sudo apt install xdotool")
        try:
            raw = await self._run_cmd("xdotool", "search", "--onlyvisible", "--name", "")
        except RuntimeError:
            return []
        active_id = ""
        try:
            active_id = await self._run_cmd("xdotool", "getactivewindow")
        except RuntimeError:
            pass
        windows: list[dict] = []
        for line in raw.splitlines():
            wid = line.strip()
            if not wid:
                continue
            try:
                name = await self._run_cmd("xdotool", "getwindowname", wid)
                if not name:
                    continue
                geo_raw = await self._run_cmd("xdotool", "getwindowgeometry", "--shell", wid)
                geo: dict[str, str] = {}
                for g in geo_raw.splitlines():
                    if "=" in g:
                        k, v = g.split("=", 1)
                        geo[k.strip()] = v.strip()
                pid_str = ""
                try:
                    pid_str = await self._run_cmd("xdotool", "getwindowpid", wid)
                except RuntimeError:
                    pass
                app_name = ""
                if pid_str:
                    try:
                        import psutil
                        app_name = psutil.Process(int(pid_str)).name()
                    except Exception:
                        pass
                windows.append({
                    "id": int(wid),
                    "title": name,
                    "app_name": app_name,
                    "x": int(geo.get("X", 0)),
                    "y": int(geo.get("Y", 0)),
                    "width": int(geo.get("WIDTH", 0)),
                    "height": int(geo.get("HEIGHT", 0)),
                    "is_focused": wid == active_id,
                })
            except (RuntimeError, ValueError):
                continue
        return windows

    async def focus_window(self, window_id: int | str) -> bool:
        if not shutil.which("xdotool"):
            raise RuntimeError("Window focus requires xdotool")
        try:
            await self._run_cmd("xdotool", "windowfocus", "--sync", str(window_id))
            await self._run_cmd("xdotool", "windowactivate", str(window_id))
            return True
        except RuntimeError as e:
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
        if not shutil.which("xdotool"):
            raise RuntimeError("Window move requires xdotool")
        try:
            await self._run_cmd("xdotool", "windowmove", str(window_id), str(x), str(y))
            if width is not None and height is not None:
                await self._run_cmd(
                    "xdotool", "windowsize", str(window_id), str(width), str(height)
                )
            return True
        except RuntimeError as e:
            logger.warning("Failed to move window %s: %s", window_id, e)
            return False

    async def minimize_window(self, window_id: int | str) -> bool:
        if not shutil.which("xdotool"):
            raise RuntimeError("Window minimize requires xdotool")
        try:
            await self._run_cmd("xdotool", "windowminimize", str(window_id))
            return True
        except RuntimeError as e:
            logger.warning("Failed to minimize window %s: %s", window_id, e)
            return False

    async def maximize_window(self, window_id: int | str) -> bool:
        if shutil.which("wmctrl"):
            try:
                await self._run_cmd(
                    "wmctrl", "-ir", str(window_id),
                    "-b", "add,maximized_vert,maximized_horz",
                )
                return True
            except RuntimeError as e:
                logger.warning("Failed to maximize window %s: %s", window_id, e)
                return False
        elif shutil.which("xdotool"):
            try:
                await self._run_cmd(
                    "xdotool", "key", "--window", str(window_id), "super+Up"
                )
                return True
            except RuntimeError as e:
                logger.warning("Failed to maximize window %s: %s", window_id, e)
                return False
        raise RuntimeError("Window maximize requires wmctrl or xdotool")

    async def close_window(self, window_id: int | str) -> bool:
        if not shutil.which("xdotool"):
            raise RuntimeError("Window close requires xdotool")
        try:
            await self._run_cmd("xdotool", "windowclose", str(window_id))
            return True
        except RuntimeError as e:
            logger.warning("Failed to close window %s: %s", window_id, e)
            return False

    # --- Keyboard & Mouse ---

    async def type_text(self, text: str, interval: float = 0.0) -> None:
        if not shutil.which("xdotool"):
            raise RuntimeError("Typing requires xdotool: sudo apt install xdotool")
        delay_ms = str(int(interval * 1000)) if interval > 0 else "0"
        await self._run_cmd("xdotool", "type", "--delay", delay_ms, text)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        if not shutil.which("xdotool"):
            raise RuntimeError("Key press requires xdotool")
        modifiers = modifiers or []
        # xdotool format: ctrl+shift+a
        parts = [m.lower() for m in modifiers] + [key.lower()]
        combo = "+".join(parts)
        await self._run_cmd("xdotool", "key", combo)

    async def mouse_move(self, x: int, y: int) -> None:
        if not shutil.which("xdotool"):
            raise RuntimeError("Mouse move requires xdotool")
        await self._run_cmd("xdotool", "mousemove", str(x), str(y))

    async def mouse_click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        if not shutil.which("xdotool"):
            raise RuntimeError("Mouse click requires xdotool")
        button_map = {"left": "1", "middle": "2", "right": "3"}
        btn = button_map.get(button, "1")
        await self.mouse_move(x, y)
        await self._run_cmd(
            "xdotool", "click", "--repeat", str(clicks), btn
        )

    async def mouse_scroll(
        self, x: int, y: int, direction: str = "down", amount: int = 3
    ) -> None:
        if not shutil.which("xdotool"):
            raise RuntimeError("Mouse scroll requires xdotool")
        await self.mouse_move(x, y)
        # xdotool: button 4 = scroll up, button 5 = scroll down
        btn = "5" if direction == "down" else "4"
        await self._run_cmd("xdotool", "click", "--repeat", str(amount), btn)

    async def capture_window_screenshot(self, window_id: int | str) -> bytes:
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            if shutil.which("import"):
                # ImageMagick import
                await self._run_cmd(
                    "import", "-window", str(window_id), tmp_path
                )
            elif shutil.which("scrot"):
                await self._run_cmd(
                    "scrot", "-w", str(window_id), tmp_path
                )
            else:
                raise RuntimeError(
                    "Window screenshot requires import (ImageMagick) or scrot"
                )
            from pathlib import Path
            data = Path(tmp_path).read_bytes()
            if not data:
                raise RuntimeError(f"Screenshot produced empty file for window {window_id}")
            return data
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
