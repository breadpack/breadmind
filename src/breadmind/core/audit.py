from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

logger = logging.getLogger("breadmind.audit")

_SENSITIVE_KEYS = frozenset({
    "api_key", "password", "token", "secret", "key", "credential",
    "authorization", "auth", "private_key", "access_token", "refresh_token",
})


def _mask_sensitive(data: dict, depth: int = 0) -> dict:
    """Recursively mask values whose keys contain sensitive identifiers."""
    if depth > 3:
        return data
    masked = {}
    for k, v in data.items():
        if any(sk in k.lower() for sk in _SENSITIVE_KEYS):
            masked[k] = "***REDACTED***"
        elif isinstance(v, dict):
            masked[k] = _mask_sensitive(v, depth + 1)
        else:
            masked[k] = v
    return masked


@dataclass
class AuditEntry:
    timestamp: str
    event_type: str  # "tool_call", "safety_check", "llm_call", "approval_request"
    user: str
    channel: str
    details: dict
    result: str  # "success", "denied", "error", "timeout"


class AuditLogger:
    """Structured audit logging for all agent actions."""

    _MAX_ENTRIES = 1000

    def __init__(self, db=None):
        self._db = db
        self._entries: list[AuditEntry] = []  # in-memory buffer

    def _create_entry(
        self, event_type: str, user: str, channel: str, details: dict, result: str,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            user=user,
            channel=channel,
            details=details,
            result=result,
        )
        self._entries.append(entry)
        if len(self._entries) > self._MAX_ENTRIES:
            half = len(self._entries) // 2
            self._entries = self._entries[half:]
        logger.info(json.dumps(asdict(entry)))
        return entry

    def log_tool_call(
        self,
        user: str,
        channel: str,
        tool_name: str,
        arguments: dict,
        result: str,
        success: bool,
        duration_ms: float,
    ) -> AuditEntry:
        """Log a tool execution."""
        return self._create_entry(
            event_type="tool_call",
            user=user,
            channel=channel,
            details={
                "tool_name": tool_name,
                "arguments": _mask_sensitive(arguments) if isinstance(arguments, dict) else arguments,
                "result": result[:1000] if isinstance(result, str) and len(result) > 1000 else result,
                "duration_ms": duration_ms,
            },
            result="success" if success else "error",
        )

    def log_safety_check(
        self,
        user: str,
        channel: str,
        action: str,
        safety_result: str,
        reason: str = "",
    ) -> AuditEntry:
        """Log a safety guard decision."""
        return self._create_entry(
            event_type="safety_check",
            user=user,
            channel=channel,
            details={
                "action": action,
                "safety_result": safety_result,
                "reason": reason,
            },
            result="denied" if safety_result == "DENIED" else "success",
        )

    def log_llm_call(
        self,
        user: str,
        channel: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit: bool,
        duration_ms: float,
    ) -> AuditEntry:
        """Log an LLM API call."""
        return self._create_entry(
            event_type="llm_call",
            user=user,
            channel=channel,
            details={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_hit": cache_hit,
                "duration_ms": duration_ms,
            },
            result="success",
        )

    def log_approval_request(
        self,
        user: str,
        channel: str,
        tool_name: str,
        status: str,
    ) -> AuditEntry:
        """Log an approval workflow event."""
        return self._create_entry(
            event_type="approval_request",
            user=user,
            channel=channel,
            details={
                "tool_name": tool_name,
                "status": status,
            },
            result=status,
        )

    def get_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Return the most recent audit entries."""
        return list(self._entries[-limit:])

    async def flush_to_db(self) -> None:
        """Persist buffered entries to database."""
        if self._db is None:
            return
        # Future: batch insert self._entries into db
        self._entries.clear()
