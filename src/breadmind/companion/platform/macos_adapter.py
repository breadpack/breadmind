"""macOS platform adapter using psutil and subprocess."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import shutil
import time
import webbrowser

from breadmind.companion.platform.base import PlatformAdapter

logger = logging.getLogger(__name__)

# macOS key code mapping for System Events
_MACOS_KEY_CODES: dict[str, int] = {
    "enter": 36, "return": 36, "tab": 48, "escape": 53, "esc": 53,
    "space": 49, "backspace": 51, "delete": 117, "forwarddelete": 117,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

# Modifier mapping for AppleScript
_MACOS_MODIFIER_MAP: dict[str, str] = {
    "ctrl": "control down",
    "alt": "option down",
    "shift": "shift down",
    "cmd": "command down",
    "command": "command down",
    "option": "option down",
    "control": "control down",
}


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

    # --- Window Management ---

    async def _run_osascript(self, script: str) -> str:
        """Run an AppleScript and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"osascript failed: {err}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def get_window_list(self) -> list[dict]:
        script = '''
        set output to ""
        tell application "System Events"
            set procs to every process whose visible is true
            repeat with p in procs
                set pName to name of p
                set isFront to (frontmost of p) as boolean
                try
                    set wins to every window of p
                    repeat with w in wins
                        set wName to name of w
                        set {px, py} to position of w
                        set {sx, sy} to size of w
                        set output to output & pName & "|||" & wName & "|||" & px & "|||" & py & "|||" & sx & "|||" & sy & "|||" & isFront & linefeed
                    end repeat
                end try
            end repeat
        end tell
        return output
        '''
        try:
            raw = await self._run_osascript(script)
        except RuntimeError as e:
            logger.warning("Failed to list windows: %s", e)
            return []
        windows: list[dict] = []
        win_id = 0
        for line in raw.splitlines():
            parts = line.split("|||")
            if len(parts) < 7:
                continue
            win_id += 1
            windows.append({
                "id": win_id,
                "title": parts[1],
                "app_name": parts[0],
                "x": int(parts[2]),
                "y": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
                "is_focused": parts[6].strip().lower() == "true",
            })
        return windows

    async def focus_window(self, window_id: int | str) -> bool:
        # window_id here is the app name or we find by index
        # For simplicity, focus by app name
        script = f'''
        tell application "System Events"
            set frontmost of process "{_escape_applescript(str(window_id))}" to true
        end tell
        '''
        try:
            await self._run_osascript(script)
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
        app_name = _escape_applescript(str(window_id))
        size_part = ""
        if width is not None and height is not None:
            size_part = f'\nset size of window 1 to {{{width}, {height}}}'
        script = f'''
        tell application "System Events"
            tell process "{app_name}"
                set position of window 1 to {{{x}, {y}}}{size_part}
            end tell
        end tell
        '''
        try:
            await self._run_osascript(script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to move window %s: %s", window_id, e)
            return False

    async def minimize_window(self, window_id: int | str) -> bool:
        app_name = _escape_applescript(str(window_id))
        script = f'''
        tell application "System Events"
            tell process "{app_name}"
                try
                    click (first button of window 1 whose subrole is "AXMinimizeButton")
                end try
            end tell
        end tell
        '''
        try:
            await self._run_osascript(script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to minimize window %s: %s", window_id, e)
            return False

    async def maximize_window(self, window_id: int | str) -> bool:
        app_name = _escape_applescript(str(window_id))
        script = f'''
        tell application "System Events"
            tell process "{app_name}"
                try
                    click (first button of window 1 whose subrole is "AXFullScreenButton")
                end try
            end tell
        end tell
        '''
        try:
            await self._run_osascript(script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to maximize window %s: %s", window_id, e)
            return False

    async def close_window(self, window_id: int | str) -> bool:
        app_name = _escape_applescript(str(window_id))
        script = f'''
        tell application "System Events"
            tell process "{app_name}"
                try
                    click (first button of window 1 whose subrole is "AXCloseButton")
                end try
            end tell
        end tell
        '''
        try:
            await self._run_osascript(script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to close window %s: %s", window_id, e)
            return False

    # --- Keyboard & Mouse ---

    async def type_text(self, text: str, interval: float = 0.0) -> None:
        escaped = _escape_applescript(text)
        delay_part = ""
        if interval > 0:
            delay_part = f" with delay {interval}"
        script = f'tell application "System Events" to keystroke "{escaped}"{delay_part}'
        try:
            await self._run_osascript(script)
        except RuntimeError as e:
            raise RuntimeError(f"Failed to type text: {e}") from e

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        modifiers = modifiers or []
        key_code = _MACOS_KEY_CODES.get(key.lower())
        using_part = ""
        if modifiers:
            mod_strs = []
            for m in modifiers:
                mapped = _MACOS_MODIFIER_MAP.get(m.lower())
                if mapped is None:
                    raise ValueError(f"Unknown modifier: {m}")
                mod_strs.append(mapped)
            using_part = f" using {{{', '.join(mod_strs)}}}"

        if key_code is not None:
            script = f'tell application "System Events" to key code {key_code}{using_part}'
        elif len(key) == 1:
            script = f'tell application "System Events" to keystroke "{_escape_applescript(key)}"{using_part}'
        else:
            raise ValueError(f"Unknown key: {key}")
        try:
            await self._run_osascript(script)
        except RuntimeError as e:
            raise RuntimeError(f"Failed to press key: {e}") from e

    async def mouse_move(self, x: int, y: int) -> None:
        if shutil.which("cliclick"):
            proc = await asyncio.create_subprocess_exec(
                "cliclick", f"m:{x},{y}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        else:
            raise RuntimeError("Mouse move requires cliclick: brew install cliclick")

    async def mouse_click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        if not shutil.which("cliclick"):
            raise RuntimeError("Mouse click requires cliclick: brew install cliclick")
        button_map = {"left": "c", "right": "rc", "middle": "c"}
        action = button_map.get(button, "c")
        if clicks == 2:
            action = "dc"  # double-click
        proc = await asyncio.create_subprocess_exec(
            "cliclick", f"{action}:{x},{y}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def mouse_scroll(
        self, x: int, y: int, direction: str = "down", amount: int = 3
    ) -> None:
        # Use AppleScript to move mouse then cliclick to scroll if available
        if not shutil.which("cliclick"):
            raise RuntimeError("Mouse scroll requires cliclick: brew install cliclick")
        await self.mouse_move(x, y)
        # cliclick scroll: positive = up, negative = down
        scroll_amount = -amount if direction == "down" else amount
        proc = await asyncio.create_subprocess_exec(
            "cliclick", f"m:{x},{y}", f"w:50",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Use osascript for scrolling as cliclick doesn't support it directly
        script = f'''
        tell application "System Events"
            scroll area 1 of window 1 of (first process whose frontmost is true) by {scroll_amount}
        end tell
        '''
        try:
            await self._run_osascript(script)
        except RuntimeError:
            logger.warning("Scroll via AppleScript failed; scrolling may not be supported")

    async def capture_window_screenshot(self, window_id: int | str) -> bytes:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # screencapture -l requires CGWindowID; use window list approach
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-l", str(window_id), tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            from pathlib import Path
            data = Path(tmp_path).read_bytes()
            if not data:
                raise RuntimeError(f"screencapture produced empty file for window {window_id}")
            return data
        finally:
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


def _escape_applescript(text: str) -> str:
    """Escape text for AppleScript string embedding."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
