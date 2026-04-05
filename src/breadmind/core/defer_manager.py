"""Defer manager for headless pause/resume sessions.

When a PreToolUse hook returns ``"defer"``, the pending tool call is
persisted and the headless session pauses.  The session can later be
resumed with ``--resume <session_id>``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class DeferStatus(str, Enum):
    DEFERRED = "deferred"
    RESUMED = "resumed"
    EXPIRED = "expired"


@dataclass
class DeferredToolCall:
    tool_name: str
    arguments: dict
    deferred_at: datetime
    session_id: str
    reason: str = ""
    status: DeferStatus = DeferStatus.DEFERRED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deferred_at"] = self.deferred_at.isoformat()
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> DeferredToolCall:
        data = dict(data)
        data["deferred_at"] = datetime.fromisoformat(data["deferred_at"])
        data["status"] = DeferStatus(data["status"])
        return cls(**data)


class DeferManager:
    """Manages deferred tool calls for headless sessions.

    When a PreToolUse hook returns ``"defer"``, the tool call is saved
    and the session pauses.  Resume with ``--resume <session_id>``.
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or Path.home() / ".breadmind" / "deferred"
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    def _path_for(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self._storage_dir / f"{safe}.json"

    def defer(self, tool_call: DeferredToolCall) -> Path:
        """Save a deferred tool call.  Returns path to defer file."""
        path = self._path_for(tool_call.session_id)
        path.write_text(json.dumps(tool_call.to_dict(), ensure_ascii=False), encoding="utf-8")
        return path

    def get_deferred(self, session_id: str) -> DeferredToolCall | None:
        """Get pending deferred call for a session."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        tc = DeferredToolCall.from_dict(data)
        if tc.status != DeferStatus.DEFERRED:
            return None
        return tc

    def resume(self, session_id: str) -> DeferredToolCall | None:
        """Mark deferred call as resumed and return it."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        tc = DeferredToolCall.from_dict(data)
        if tc.status != DeferStatus.DEFERRED:
            return None
        tc.status = DeferStatus.RESUMED
        path.write_text(json.dumps(tc.to_dict(), ensure_ascii=False), encoding="utf-8")
        return tc

    def list_pending(self) -> list[DeferredToolCall]:
        """List all pending deferred calls."""
        results: list[DeferredToolCall] = []
        for p in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                tc = DeferredToolCall.from_dict(data)
                if tc.status == DeferStatus.DEFERRED:
                    results.append(tc)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return results

    def expire_old(self, max_age_hours: int = 24) -> int:
        """Expire deferred calls older than *max_age_hours*.  Returns count expired."""
        now = datetime.now(timezone.utc)
        expired = 0
        for p in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                tc = DeferredToolCall.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if tc.status != DeferStatus.DEFERRED:
                continue
            age_dt = tc.deferred_at
            if age_dt.tzinfo is None:
                age_dt = age_dt.replace(tzinfo=timezone.utc)
            delta = now - age_dt
            if delta.total_seconds() > max_age_hours * 3600:
                tc.status = DeferStatus.EXPIRED
                p.write_text(json.dumps(tc.to_dict(), ensure_ascii=False), encoding="utf-8")
                expired += 1
        return expired
