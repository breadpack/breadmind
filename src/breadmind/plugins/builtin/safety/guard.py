from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

DESTRUCTIVE_PATTERNS = [
    r"\bdelete\b", r"\bremove\b", r"\bdrop\b", r"\bkill\b",
    r"\brestart\b", r"\breboot\b", r"\bstop\b", r"\bdestroy\b",
    r"\brm\s", r"\bshutdown\b",
]

DESTRUCTIVE_TOOLS = frozenset({
    "k8s_pods_delete", "proxmox_delete_vm", "proxmox_delete_lxc",
    "proxmox_stop_vm", "proxmox_reboot_vm", "proxmox_shutdown_vm",
})


@dataclass
class SafetyVerdict:
    """안전 검사 결과."""
    allowed: bool
    needs_approval: bool = False
    reason: str = ""


class SafetyGuard:
    """autonomy level 기반 안전장치."""

    def __init__(self, autonomy: str = "confirm-destructive",
                 blocked_patterns: list[str] | None = None,
                 approve_required: list[str] | None = None) -> None:
        self._autonomy = autonomy
        self._blocked = [re.compile(re.escape(p)) for p in (blocked_patterns or [])]
        self._approve_required = set(approve_required or [])

    def check(self, tool_name: str, arguments: dict[str, Any]) -> SafetyVerdict:
        args_str = str(arguments)
        for pattern in self._blocked:
            if pattern.search(args_str):
                return SafetyVerdict(allowed=False, reason=f"Blocked pattern matched: {pattern.pattern}")

        if self._autonomy == "auto":
            return SafetyVerdict(allowed=True)

        if self._autonomy == "confirm-all":
            return SafetyVerdict(allowed=True, needs_approval=True, reason="confirm-all mode")

        if tool_name in self._approve_required:
            return SafetyVerdict(allowed=True, needs_approval=True, reason=f"Tool '{tool_name}' requires approval")

        if self._is_destructive(tool_name, arguments):
            return SafetyVerdict(allowed=True, needs_approval=True, reason="Destructive action detected")

        if self._autonomy == "confirm-unsafe" and self._is_external(tool_name):
            return SafetyVerdict(allowed=True, needs_approval=True, reason="External action in confirm-unsafe mode")

        return SafetyVerdict(allowed=True)

    def _is_destructive(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if tool_name in DESTRUCTIVE_TOOLS:
            return True
        args_str = str(arguments).lower()
        return any(re.search(p, args_str) for p in DESTRUCTIVE_PATTERNS)

    def _is_external(self, tool_name: str) -> bool:
        return tool_name in {"web_search", "web_fetch", "shell_exec", "file_write"}
