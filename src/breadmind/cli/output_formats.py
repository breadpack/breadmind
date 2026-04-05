"""Headless output formats: text, json, stream-json.

Supports three output modes for headless/CI usage:
- ``text``  -- plain human-readable text (default)
- ``json``  -- single JSON object emitted after completion
- ``stream-json`` -- newline-delimited JSON events in real time
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TextIO


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    STREAM_JSON = "stream-json"


@dataclass
class StreamEvent:
    """A single output event."""

    type: str  # "start", "text_delta", "tool_use", "tool_result", "error", "complete"
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


class OutputFormatter:
    """Formats agent output based on selected format."""

    def __init__(
        self,
        fmt: OutputFormat = OutputFormat.TEXT,
        stream: TextIO | None = None,
    ) -> None:
        self._format = fmt
        self._stream = stream or sys.stdout
        self._events: list[StreamEvent] = []
        self._result: dict = {}

    @property
    def format(self) -> OutputFormat:
        return self._format

    @property
    def events(self) -> list[StreamEvent]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Emit helpers
    # ------------------------------------------------------------------

    def emit_start(self, session_id: str | None = None) -> None:
        """Emit session start event."""
        event = StreamEvent(type="start", data={"session_id": session_id})
        self._handle_event(event)

    def emit_text(self, text: str) -> None:
        """Emit text delta."""
        event = StreamEvent(type="text_delta", data={"text": text})
        self._handle_event(event)

    def emit_tool_use(self, tool_name: str, arguments: dict) -> None:
        event = StreamEvent(
            type="tool_use",
            data={"tool_name": tool_name, "arguments": arguments},
        )
        self._handle_event(event)

    def emit_tool_result(
        self, tool_name: str, result: str, success: bool = True
    ) -> None:
        event = StreamEvent(
            type="tool_result",
            data={"tool_name": tool_name, "result": result, "success": success},
        )
        self._handle_event(event)

    def emit_error(self, error: str) -> None:
        event = StreamEvent(type="error", data={"error": error})
        self._handle_event(event)

    def emit_complete(
        self,
        result: str,
        cost: dict | None = None,
        session_id: str | None = None,
    ) -> None:
        """Emit completion. For JSON mode, writes the accumulated result."""
        event = StreamEvent(
            type="complete",
            data={"result": result, "cost": cost, "session_id": session_id},
        )
        self._handle_event(event)

        if self._format == OutputFormat.JSON:
            self._write_json_result(result, cost, session_id)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _handle_event(self, event: StreamEvent) -> None:
        self._events.append(event)

        if self._format == OutputFormat.TEXT:
            self._write_text_event(event)
        elif self._format == OutputFormat.STREAM_JSON:
            self._write_stream_event(event)
        # JSON mode accumulates; output happens in emit_complete

    def _write_text_event(self, event: StreamEvent) -> None:
        if event.type == "text_delta":
            self._stream.write(event.data.get("text", ""))
            self._stream.flush()
        elif event.type == "tool_use":
            tool = event.data.get("tool_name", "")
            self._stream.write(f"\n[tool_use] {tool}\n")
            self._stream.flush()
        elif event.type == "tool_result":
            tool = event.data.get("tool_name", "")
            success = event.data.get("success", True)
            status = "ok" if success else "error"
            self._stream.write(f"[tool_result] {tool}: {status}\n")
            self._stream.flush()
        elif event.type == "error":
            self._stream.write(f"ERROR: {event.data.get('error', '')}\n")
            self._stream.flush()
        elif event.type == "complete":
            result = event.data.get("result", "")
            self._stream.write(f"\n{result}\n")
            self._stream.flush()

    def _write_stream_event(self, event: StreamEvent) -> None:
        """Write a single NDJSON line for stream-json mode."""
        line = json.dumps(asdict(event), ensure_ascii=False)
        self._stream.write(line + "\n")
        self._stream.flush()

    def _write_json_result(
        self,
        result: str,
        cost: dict | None,
        session_id: str | None,
    ) -> None:
        """Write the final aggregated JSON object."""
        output = {
            "result": result,
            "cost": cost,
            "session_id": session_id,
            "events": [asdict(e) for e in self._events],
        }
        self._stream.write(json.dumps(output, ensure_ascii=False) + "\n")
        self._stream.flush()
