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
    }
