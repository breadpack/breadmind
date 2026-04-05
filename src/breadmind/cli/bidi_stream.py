"""Bidirectional NDJSON streaming for programmatic interaction."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, TextIO


class StreamMessageType(str, Enum):
    # Inbound (client -> agent)
    USER_MESSAGE = "user_message"
    TOOL_RESULT = "tool_result"
    CONTROL = "control"  # pause, resume, cancel

    # Outbound (agent -> client)
    ASSISTANT_TEXT = "assistant_text"
    TOOL_USE = "tool_use"
    STATUS = "status"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class StreamMessage:
    type: StreamMessageType
    data: dict = field(default_factory=dict)
    id: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {"type": self.type.value, "data": self.data, "id": self.id}
        )

    @classmethod
    def from_json(cls, line: str) -> StreamMessage:
        raw = json.loads(line)
        return cls(
            type=StreamMessageType(raw["type"]),
            data=raw.get("data", {}),
            id=raw.get("id", ""),
        )


class BidiStreamHandler:
    """Bidirectional NDJSON streaming for programmatic interaction.

    Input format (stdin): one JSON object per line
    Output format (stdout): one JSON object per line

    Supports:
    - User messages from stdin
    - Tool results injected via stdin
    - Control signals (pause/resume/cancel)
    - Chaining: output of one instance can feed input of another
    """

    def __init__(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._running = False

    def emit(self, msg: StreamMessage) -> None:
        """Write a message to the output stream."""
        self._output.write(msg.to_json() + "\n")
        self._output.flush()

    def emit_text(self, text: str) -> None:
        self.emit(
            StreamMessage(
                type=StreamMessageType.ASSISTANT_TEXT,
                data={"text": text},
                id=uuid.uuid4().hex[:8],
            )
        )

    def emit_tool_use(
        self, tool_name: str, arguments: dict, tool_use_id: str = ""
    ) -> None:
        self.emit(
            StreamMessage(
                type=StreamMessageType.TOOL_USE,
                data={
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "tool_use_id": tool_use_id or uuid.uuid4().hex[:8],
                },
                id=uuid.uuid4().hex[:8],
            )
        )

    def emit_error(self, error: str) -> None:
        self.emit(
            StreamMessage(
                type=StreamMessageType.ERROR,
                data={"error": error},
                id=uuid.uuid4().hex[:8],
            )
        )

    def emit_complete(self, result: str = "") -> None:
        self.emit(
            StreamMessage(
                type=StreamMessageType.COMPLETE,
                data={"result": result},
                id=uuid.uuid4().hex[:8],
            )
        )

    async def read_messages(self) -> AsyncIterator[StreamMessage]:
        """Read messages from input stream asynchronously."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, self._input.readline)
            except (OSError, ValueError):
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                yield StreamMessage.from_json(line)
            except (json.JSONDecodeError, KeyError, ValueError):
                self.emit_error(f"Invalid message: {line}")

    async def read_one(self, timeout: float | None = None) -> StreamMessage | None:
        """Read a single message with optional timeout."""
        loop = asyncio.get_event_loop()

        async def _read() -> StreamMessage | None:
            line = await loop.run_in_executor(None, self._input.readline)
            if not line:
                return None
            line = line.strip()
            if not line:
                return None
            return StreamMessage.from_json(line)

        try:
            if timeout is not None:
                return await asyncio.wait_for(_read(), timeout=timeout)
            return await _read()
        except asyncio.TimeoutError:
            return None
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
