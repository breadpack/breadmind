from __future__ import annotations
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from breadmind.plugins.builtin.safety.audit import AuditLog
    from breadmind.plugins.builtin.safety.auto_classifier import AutoSafetyClassifier

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
                 approve_required: list[str] | None = None,
                 audit_log: AuditLog | None = None,
                 auto_classifier: AutoSafetyClassifier | None = None) -> None:
        self._autonomy = autonomy
        self._blocked = [re.compile(re.escape(p)) for p in (blocked_patterns or [])]
        self._approve_required = set(approve_required or [])
        self._audit_log = audit_log
        self._auto_classifier = auto_classifier

    def check(self, tool_name: str, arguments: dict[str, Any],
              user: str = "", trace_id: str | None = None) -> SafetyVerdict:
        start = time.monotonic()

        args_str = str(arguments)
        for pattern in self._blocked:
            if pattern.search(args_str):
                verdict = SafetyVerdict(allowed=False, reason=f"Blocked pattern matched: {pattern.pattern}")
                self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
                return verdict

        if self._autonomy == "auto":
            verdict = SafetyVerdict(allowed=True)
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        if self._autonomy == "confirm-all":
            verdict = SafetyVerdict(allowed=True, needs_approval=True, reason="confirm-all mode")
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        if tool_name in self._approve_required:
            verdict = SafetyVerdict(allowed=True, needs_approval=True, reason=f"Tool '{tool_name}' requires approval")
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        if self._is_destructive(tool_name, arguments):
            verdict = SafetyVerdict(allowed=True, needs_approval=True, reason="Destructive action detected")
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        if self._autonomy == "confirm-unsafe" and self._is_external(tool_name):
            verdict = SafetyVerdict(allowed=True, needs_approval=True, reason="External action in confirm-unsafe mode")
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        verdict = SafetyVerdict(allowed=True)
        self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
        return verdict

    async def check_async(self, tool_name: str, arguments: dict[str, Any],
                         user: str = "", trace_id: str | None = None,
                         context: str = "") -> SafetyVerdict:
        """Async version of :meth:`check` with ``auto-llm`` support.

        When ``autonomy="auto-llm"`` and an ``auto_classifier`` is configured,
        the LLM-based classifier is consulted instead of pattern matching.
        For all other autonomy modes the behaviour is identical to :meth:`check`.
        """
        start = time.monotonic()

        # Blocked-pattern check always runs first (sync, fast)
        args_str = str(arguments)
        for pattern in self._blocked:
            if pattern.search(args_str):
                verdict = SafetyVerdict(allowed=False, reason=f"Blocked pattern matched: {pattern.pattern}")
                self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
                return verdict

        if self._autonomy == "auto-llm" and self._auto_classifier is not None:
            classification = await self._auto_classifier.classify(
                tool_name, arguments, context=context,
            )
            if classification.suggested_action == "allow":
                verdict = SafetyVerdict(allowed=True)
            elif classification.suggested_action == "deny":
                verdict = SafetyVerdict(allowed=False, reason=classification.reason)
            else:  # "ask_user"
                verdict = SafetyVerdict(
                    allowed=True, needs_approval=True, reason=classification.reason,
                )
            self._record_audit(tool_name, arguments, verdict, user, trace_id, start)
            return verdict

        # Fall back to synchronous logic for all other modes
        return self.check(tool_name, arguments, user=user, trace_id=trace_id)

    def _record_audit(self, tool_name: str, arguments: dict[str, Any],
                      verdict: SafetyVerdict, user: str,
                      trace_id: str | None, start: float) -> None:
        """감사 로그에 판정 결과를 기록한다."""
        if self._audit_log is None:
            return

        from breadmind.plugins.builtin.safety.audit import AuditEntry

        duration_ms = (time.monotonic() - start) * 1000

        if not verdict.allowed:
            verdict_str = "deny"
        elif verdict.needs_approval:
            verdict_str = "approve_required"
        else:
            verdict_str = "allow"

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            trace_id=trace_id,
            user=user,
            tool_name=tool_name,
            arguments=arguments,
            verdict=verdict_str,
            reason=verdict.reason,
            approved=None if verdict.needs_approval else (verdict.allowed or None),
            duration_ms=duration_ms,
        )
        self._audit_log.record(entry)

    def _is_destructive(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if tool_name in DESTRUCTIVE_TOOLS:
            return True
        args_str = str(arguments).lower()
        return any(re.search(p, args_str) for p in DESTRUCTIVE_PATTERNS)

    def _is_external(self, tool_name: str) -> bool:
        return tool_name in {"web_search", "web_fetch", "shell_exec", "file_write"}
