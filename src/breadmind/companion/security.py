"""Permission management and path sandboxing for companion tools."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Capability flags that control groups of tools
_DEFAULT_CAPABILITIES: dict[str, bool] = {
    "window_mgmt": True,
    "input_control": False,
}

# Default permission policy: what's allowed out of the box
_DEFAULT_PERMISSIONS: dict[str, Any] = {
    "companion_system_info": True,
    "companion_process_list": True,
    "companion_network_info": True,
    "companion_screenshot": True,
    "companion_notify": True,
    "companion_open_url": True,
    "companion_file_list": True,
    "companion_file_read": True,
    # Window management (read-only listing is safe)
    "companion_window_list": True,
    "companion_window_focus": True,
    "companion_window_move": True,
    "companion_window_minimize": True,
    "companion_window_maximize": True,
    "companion_window_close": False,
    "companion_window_screenshot": True,
    # Input control (keyboard/mouse is sensitive, denied by default)
    "companion_type_text": False,
    "companion_press_key": False,
    "companion_mouse_move": False,
    "companion_mouse_click": False,
    "companion_mouse_scroll": False,
    "companion_mouse_drag": False,
    # Denied by default (destructive or sensitive)
    "companion_clipboard_read": False,
    "companion_clipboard_write": False,
    "companion_process_kill": False,
    "companion_power": False,
}

# Tools that always require explicit confirmation
_CONFIRMATION_REQUIRED = {
    "companion_power",
    "companion_process_kill",
    "companion_window_close",
    "companion_type_text",
    "companion_press_key",
    "companion_mouse_click",
    "companion_mouse_drag",
}

# Mapping from capability flags to tool names they control
_CAPABILITY_TOOL_MAP: dict[str, list[str]] = {
    "window_mgmt": [
        "companion_window_list",
        "companion_window_focus",
        "companion_window_move",
        "companion_window_minimize",
        "companion_window_maximize",
        "companion_window_close",
        "companion_window_screenshot",
    ],
    "input_control": [
        "companion_type_text",
        "companion_press_key",
        "companion_mouse_move",
        "companion_mouse_click",
        "companion_mouse_scroll",
        "companion_mouse_drag",
    ],
}


class PermissionManager:
    """Controls which companion tools are allowed to execute."""

    def __init__(
        self,
        capabilities: dict[str, Any] | None = None,
        allowed_paths: list[str] | None = None,
        denied_paths: list[str] | None = None,
    ) -> None:
        self._permissions: dict[str, Any] = dict(_DEFAULT_PERMISSIONS)
        if capabilities:
            # Apply capability group flags first (e.g. input_control=True enables all input tools)
            for cap_name, tools in _CAPABILITY_TOOL_MAP.items():
                if cap_name in capabilities:
                    enabled = bool(capabilities[cap_name])
                    for tool_name in tools:
                        self._permissions[tool_name] = enabled
            # Then apply per-tool overrides
            for key, value in capabilities.items():
                if key not in _CAPABILITY_TOOL_MAP:
                    self._permissions[key] = value
        self._allowed_paths = [Path(p).resolve() for p in (allowed_paths or [])]
        self._denied_paths = [Path(p).resolve() for p in (denied_paths or [])]

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is permitted by the current policy."""
        return bool(self._permissions.get(tool_name, False))

    def check_path(self, path: str) -> bool:
        """Validate that a file path is within allowed boundaries.

        Rules:
        1. Resolve symlinks to prevent traversal attacks
        2. If allowed_paths is set, path must be under one of them
        3. Path must NOT be under any denied_path
        4. If no allowed_paths are configured, allow everything not denied
        """
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            return False

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                resolved.relative_to(denied)
                logger.debug("Path %s denied (under %s)", path, denied)
                return False
            except ValueError:
                continue

        # If allowed_paths are configured, path must be under one
        if self._allowed_paths:
            for allowed in self._allowed_paths:
                try:
                    resolved.relative_to(allowed)
                    return True
                except ValueError:
                    continue
            logger.debug("Path %s not under any allowed path", path)
            return False

        return True

    def requires_confirmation(self, tool_name: str) -> bool:
        """Check if a tool requires user confirmation before execution."""
        return tool_name in _CONFIRMATION_REQUIRED


async def confirm_action(description: str) -> bool:
    """Prompt for confirmation on stdin (CLI mode only)."""
    import asyncio
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(
        None, lambda: input(f"[Confirm] {description} (y/N): ").strip().lower()
    )
    return answer in ("y", "yes")
