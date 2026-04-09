"""Permission management and path sandboxing for companion tools."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
            self._permissions.update(capabilities)
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
