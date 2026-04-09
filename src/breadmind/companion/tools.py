"""Companion tools: device-specific operations invoked by Commander."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from breadmind.companion.platform.base import PlatformAdapter
from breadmind.companion.security import PermissionManager

logger = logging.getLogger(__name__)


async def companion_system_info(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Full system information: OS, CPU, RAM, disk, battery."""
    info = await platform_adapter.get_system_info()
    cpu = await platform_adapter.get_cpu_info()
    mem = await platform_adapter.get_memory_info()
    disks = await platform_adapter.get_disk_info()
    battery = await platform_adapter.get_battery_info()
    return {
        "system": info,
        "cpu": cpu,
        "memory": mem,
        "disks": disks,
        "battery": battery,
    }


async def companion_process_list(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Top processes sorted by CPU or memory."""
    sort_by = args.get("sort_by", "cpu")
    procs = await platform_adapter.get_process_list(sort_by=sort_by)
    return {"processes": procs, "count": len(procs)}


async def companion_process_kill(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Kill a process by PID."""
    pid = args.get("pid")
    if pid is None:
        return {"error": "pid is required"}
    force = args.get("force", False)
    success = await platform_adapter.kill_process(int(pid), force=force)
    return {"pid": pid, "killed": success}


async def companion_network_info(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Network interfaces and addresses."""
    interfaces = await platform_adapter.get_network_interfaces()
    return {"interfaces": interfaces}


async def companion_screenshot(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Capture screenshot and return as base64-encoded PNG."""
    png_bytes = await platform_adapter.capture_screenshot()
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return {"image_base64": encoded, "format": "png", "size_bytes": len(png_bytes)}


async def companion_clipboard_read(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Read current clipboard content."""
    text = await platform_adapter.get_clipboard()
    return {"text": text}


async def companion_clipboard_write(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Write text to clipboard."""
    text = args.get("text", "")
    await platform_adapter.set_clipboard(text)
    return {"written": True, "length": len(text)}


async def companion_open_url(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Open a URL in the default browser."""
    url = args.get("url", "")
    if not url:
        return {"error": "url is required"}
    await platform_adapter.open_url(url)
    return {"opened": True, "url": url}


async def companion_notify(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Send a desktop notification."""
    title = args.get("title", "BreadMind")
    body = args.get("body", "")
    await platform_adapter.send_notification(title, body)
    return {"sent": True}


async def companion_power(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Execute a power action (sleep, shutdown, lock)."""
    action = args.get("action", "")
    if action not in ("sleep", "shutdown", "lock"):
        return {"error": f"Invalid power action: {action}. Use: sleep, shutdown, lock"}
    await platform_adapter.power_action(action)
    return {"action": action, "executed": True}


async def companion_file_read(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Read a file (sandboxed to allowed paths)."""
    file_path = args.get("path", "")
    if not file_path:
        return {"error": "path is required"}
    if not permissions.check_path(file_path):
        return {"error": f"Access denied: {file_path}"}
    try:
        resolved = Path(file_path).resolve()
        content = resolved.read_text(encoding="utf-8", errors="replace")
        # Limit output size
        max_size = args.get("max_size", 100_000)
        if len(content) > max_size:
            content = content[:max_size] + f"\n... (truncated, {len(content)} total chars)"
        return {"path": str(resolved), "content": content, "size": resolved.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


async def companion_file_list(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """List directory contents (sandboxed to allowed paths)."""
    dir_path = args.get("path", "")
    if not dir_path:
        return {"error": "path is required"}
    if not permissions.check_path(dir_path):
        return {"error": f"Access denied: {dir_path}"}
    try:
        resolved = Path(dir_path).resolve()
        if not resolved.is_dir():
            return {"error": f"Not a directory: {dir_path}"}
        entries = []
        for entry in sorted(resolved.iterdir()):
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else 0,
                    "modified": stat.st_mtime,
                })
            except PermissionError:
                entries.append({"name": entry.name, "is_dir": False, "error": "permission denied"})
        return {"path": str(resolved), "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"error": str(e)}


async def companion_window_list(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """List all visible windows."""
    windows = await platform_adapter.get_window_list()
    return {"windows": windows, "count": len(windows)}


async def companion_window_focus(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Focus a window by ID."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    success = await platform_adapter.focus_window(window_id)
    return {"window_id": window_id, "focused": success}


async def companion_window_move(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Move/resize a window."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    x = args.get("x")
    y = args.get("y")
    if x is None or y is None:
        return {"error": "x and y are required"}
    width = args.get("width")
    height = args.get("height")
    success = await platform_adapter.move_window(window_id, int(x), int(y), width, height)
    return {"window_id": window_id, "moved": success}


async def companion_window_minimize(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Minimize a window."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    success = await platform_adapter.minimize_window(window_id)
    return {"window_id": window_id, "minimized": success}


async def companion_window_maximize(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Maximize a window."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    success = await platform_adapter.maximize_window(window_id)
    return {"window_id": window_id, "maximized": success}


async def companion_window_close(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Close a window."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    success = await platform_adapter.close_window(window_id)
    return {"window_id": window_id, "closed": success}


async def companion_window_screenshot(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Capture a screenshot of a specific window."""
    window_id = args.get("window_id")
    if window_id is None:
        return {"error": "window_id is required"}
    png_bytes = await platform_adapter.capture_window_screenshot(window_id)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return {"image_base64": encoded, "format": "png", "size_bytes": len(png_bytes)}


async def companion_type_text(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Type text at the current cursor position."""
    text = args.get("text", "")
    if not text:
        return {"error": "text is required"}
    interval = float(args.get("interval", 0.0))
    await platform_adapter.type_text(text, interval=interval)
    return {"typed": True, "length": len(text)}


async def companion_press_key(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Press a key combination."""
    key = args.get("key", "")
    if not key:
        return {"error": "key is required"}
    modifiers = args.get("modifiers")
    await platform_adapter.press_key(key, modifiers=modifiers)
    return {"pressed": True, "key": key, "modifiers": modifiers or []}


async def companion_mouse_move(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Move mouse cursor to coordinates."""
    x = args.get("x")
    y = args.get("y")
    if x is None or y is None:
        return {"error": "x and y are required"}
    await platform_adapter.mouse_move(int(x), int(y))
    return {"moved": True, "x": int(x), "y": int(y)}


async def companion_mouse_click(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Click at a screen position."""
    x = args.get("x")
    y = args.get("y")
    if x is None or y is None:
        return {"error": "x and y are required"}
    button = args.get("button", "left")
    clicks = int(args.get("clicks", 1))
    await platform_adapter.mouse_click(int(x), int(y), button=button, clicks=clicks)
    return {"clicked": True, "x": int(x), "y": int(y), "button": button, "clicks": clicks}


async def companion_mouse_scroll(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Scroll at a screen position."""
    x = args.get("x")
    y = args.get("y")
    if x is None or y is None:
        return {"error": "x and y are required"}
    direction = args.get("direction", "down")
    amount = int(args.get("amount", 3))
    await platform_adapter.mouse_scroll(int(x), int(y), direction=direction, amount=amount)
    return {"scrolled": True, "x": int(x), "y": int(y), "direction": direction, "amount": amount}


async def companion_mouse_drag(
    platform_adapter: PlatformAdapter,
    permissions: PermissionManager,
    args: dict[str, Any],
) -> dict:
    """Drag from one position to another."""
    from_x = args.get("from_x")
    from_y = args.get("from_y")
    to_x = args.get("to_x")
    to_y = args.get("to_y")
    if any(v is None for v in (from_x, from_y, to_x, to_y)):
        return {"error": "from_x, from_y, to_x, to_y are required"}
    button = args.get("button", "left")
    duration = float(args.get("duration", 0.5))
    await platform_adapter.mouse_drag(
        int(from_x), int(from_y), int(to_x), int(to_y),
        button=button, duration=duration,
    )
    return {
        "dragged": True,
        "from": {"x": int(from_x), "y": int(from_y)},
        "to": {"x": int(to_x), "y": int(to_y)},
        "button": button,
    }


def get_all_tools() -> dict[str, Any]:
    """Return a dict of all companion tool functions keyed by name."""
    return {
        "companion_system_info": companion_system_info,
        "companion_process_list": companion_process_list,
        "companion_process_kill": companion_process_kill,
        "companion_network_info": companion_network_info,
        "companion_screenshot": companion_screenshot,
        "companion_clipboard_read": companion_clipboard_read,
        "companion_clipboard_write": companion_clipboard_write,
        "companion_open_url": companion_open_url,
        "companion_notify": companion_notify,
        "companion_power": companion_power,
        "companion_file_read": companion_file_read,
        "companion_file_list": companion_file_list,
        "companion_window_list": companion_window_list,
        "companion_window_focus": companion_window_focus,
        "companion_window_move": companion_window_move,
        "companion_window_minimize": companion_window_minimize,
        "companion_window_maximize": companion_window_maximize,
        "companion_window_close": companion_window_close,
        "companion_window_screenshot": companion_window_screenshot,
        "companion_type_text": companion_type_text,
        "companion_press_key": companion_press_key,
        "companion_mouse_move": companion_mouse_move,
        "companion_mouse_click": companion_mouse_click,
        "companion_mouse_scroll": companion_mouse_scroll,
        "companion_mouse_drag": companion_mouse_drag,
    }
