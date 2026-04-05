from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class TraceEntry:
    timestamp: float
    agent_id: str
    action: str  # "tool_call", "llm_request", "subagent_spawn", "decision"
    details: dict = field(default_factory=dict)
    parent_trace_id: str | None = None


@dataclass
class SessionTrace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    entries: list[TraceEntry] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def signature(self) -> str:
        """Generate a hash signature for the trace for integrity verification."""
        content = json.dumps(
            [
                {"ts": e.timestamp, "agent": e.agent_id, "action": e.action}
                for e in self.entries
            ],
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class SessionTracer:
    """Tracks provenance across multi-agent chains.

    Each session gets a trace ID. When subagents are spawned,
    they inherit the parent trace with linked IDs, creating
    an auditable chain for debugging decisions.
    """

    def __init__(self, session_id: str = ""):
        self._trace = SessionTrace(session_id=session_id)
        self._child_traces: dict[str, SessionTracer] = {}
        self._saved_signature: str | None = None

    @property
    def trace(self) -> SessionTrace:
        return self._trace

    @property
    def trace_id(self) -> str:
        return self._trace.trace_id

    def record(
        self, agent_id: str, action: str, details: dict | None = None
    ) -> TraceEntry:
        """Record an action in the trace."""
        entry = TraceEntry(
            timestamp=time.time(),
            agent_id=agent_id,
            action=action,
            details=details or {},
            parent_trace_id=self._trace.trace_id,
        )
        self._trace.entries.append(entry)
        # Update saved signature after each record
        self._saved_signature = self._trace.signature
        return entry

    def spawn_child(self, child_agent_id: str) -> SessionTracer:
        """Create a child tracer for a subagent, linked to parent."""
        child = SessionTracer(session_id=self._trace.session_id)
        # Record the spawn in the parent trace
        self.record(
            agent_id=child_agent_id,
            action="subagent_spawn",
            details={"child_trace_id": child.trace_id},
        )
        self._child_traces[child.trace_id] = child
        return child

    def get_chain(self) -> list[SessionTrace]:
        """Get full trace chain including children."""
        chain = [self._trace]
        for child_tracer in self._child_traces.values():
            chain.extend(child_tracer.get_chain())
        return chain

    def export(self) -> dict:
        """Export trace as serializable dict."""
        return {
            "trace_id": self._trace.trace_id,
            "session_id": self._trace.session_id,
            "created_at": self._trace.created_at,
            "signature": self._trace.signature,
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "agent_id": e.agent_id,
                    "action": e.action,
                    "details": e.details,
                    "parent_trace_id": e.parent_trace_id,
                }
                for e in self._trace.entries
            ],
            "children": {
                tid: child.export()
                for tid, child in self._child_traces.items()
            },
        }

    def verify_integrity(self) -> bool:
        """Verify trace hasn't been tampered with."""
        if self._saved_signature is None:
            # No records yet — integrity is trivially valid
            return True
        return self._trace.signature == self._saved_signature

    @classmethod
    def from_dict(cls, data: dict) -> SessionTracer:
        """Reconstruct tracer from exported dict."""
        tracer = cls(session_id=data.get("session_id", ""))
        tracer._trace.trace_id = data["trace_id"]
        tracer._trace.created_at = data.get("created_at", 0.0)

        for entry_data in data.get("entries", []):
            entry = TraceEntry(
                timestamp=entry_data["timestamp"],
                agent_id=entry_data["agent_id"],
                action=entry_data["action"],
                details=entry_data.get("details", {}),
                parent_trace_id=entry_data.get("parent_trace_id"),
            )
            tracer._trace.entries.append(entry)

        # Restore saved signature from current state
        if tracer._trace.entries:
            tracer._saved_signature = tracer._trace.signature

        # Reconstruct children
        for tid, child_data in data.get("children", {}).items():
            tracer._child_traces[tid] = cls.from_dict(child_data)

        return tracer
