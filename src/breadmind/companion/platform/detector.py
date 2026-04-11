"""Detect the current platform and return the appropriate adapter."""

from __future__ import annotations

import sys

from breadmind.companion.platform.base import PlatformAdapter


def detect_platform() -> PlatformAdapter:
    """Return the correct PlatformAdapter for the current OS."""
    if sys.platform == "win32":
        from breadmind.companion.platform.windows_adapter import WindowsAdapter
        return WindowsAdapter()
    elif sys.platform == "darwin":
        from breadmind.companion.platform.macos_adapter import MacOSAdapter
        return MacOSAdapter()
    else:
        from breadmind.companion.platform.linux_adapter import LinuxAdapter
        return LinuxAdapter()
