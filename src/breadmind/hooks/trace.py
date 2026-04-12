from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class HookTraceEntry:
    timestamp: float
    hook_id: str
    event: str
    decision: str       # "proceed" | "block" | "modify" | "reply" | "reroute"
    duration_ms: float
    reason: str = ""
    error: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HookTraceBuffer:
    """In-memory ring buffer of recent hook executions."""

    def __init__(self, max_entries: int = 500) -> None:
        self._buf: deque[HookTraceEntry] = deque(maxlen=max_entries)
        self._subscribers: set[Any] = set()

    def record(self, entry: HookTraceEntry) -> None:
        self._buf.append(entry)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(entry)
            except Exception:
                pass

    def recent(
        self, limit: int = 100, *, event: str | None = None,
        hook_id: str | None = None,
    ) -> list[HookTraceEntry]:
        entries = list(self._buf)
        if event:
            entries = [e for e in entries if e.event == event]
        if hook_id:
            entries = [e for e in entries if e.hook_id == hook_id]
        return entries[-limit:]

    def stats(self) -> list[dict[str, Any]]:
        by_hook: dict[str, dict[str, Any]] = {}
        for e in self._buf:
            stat = by_hook.setdefault(e.hook_id, {
                "hook_id": e.hook_id,
                "total": 0,
                "block_count": 0,
                "modify_count": 0,
                "reply_count": 0,
                "error_count": 0,
                "total_duration_ms": 0.0,
            })
            stat["total"] += 1
            stat["total_duration_ms"] += e.duration_ms
            if e.decision == "block":
                stat["block_count"] += 1
            elif e.decision == "modify":
                stat["modify_count"] += 1
            elif e.decision == "reply":
                stat["reply_count"] += 1
            if e.error:
                stat["error_count"] += 1
        out = []
        for stat in by_hook.values():
            stat["avg_duration_ms"] = (
                stat["total_duration_ms"] / stat["total"] if stat["total"] else 0.0
            )
            out.append(stat)
        return out

    def subscribe(self, queue: Any) -> None:
        self._subscribers.add(queue)

    def unsubscribe(self, queue: Any) -> None:
        self._subscribers.discard(queue)


_global_buffer: HookTraceBuffer | None = None


def get_trace_buffer() -> HookTraceBuffer:
    global _global_buffer
    if _global_buffer is None:
        _global_buffer = HookTraceBuffer()
    return _global_buffer
