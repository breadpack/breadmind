"""Platform adapters for companion agent."""

from breadmind.companion.platform.base import PlatformAdapter
from breadmind.companion.platform.detector import detect_platform

__all__ = ["PlatformAdapter", "detect_platform"]
