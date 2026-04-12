"""BidiStreamHandler unit tests."""
from __future__ import annotations

import io
import json

import pytest

from breadmind.cli.bidi_stream import (
    BidiStreamHandler,
    StreamMessage,
    StreamMessageType,
)


@pytest.fixture
def streams():
    """Return (handler, output_buffer) with writable output and controlled input."""
    inp = io.StringIO()
    out = io.StringIO()
    handler = BidiStreamHandler(input_stream=inp, output_stream=out)
    return handler, out, inp


# ── StreamMessage ───────────────────────────────────────────────────


class TestStreamMessage:
    def test_to_json_roundtrip(self):
        msg = StreamMessage(
            type=StreamMessageType.USER_MESSAGE,
            data={"text": "hello"},
            id="abc",
        )
        json_str = msg.to_json()
        restored = StreamMessage.from_json(json_str)
        assert restored.type == StreamMessageType.USER_MESSAGE
        assert restored.data == {"text": "hello"}
        assert restored.id == "abc"

    def test_from_json_minimal(self):
        raw = json.dumps({"type": "error", "data": {"error": "oops"}})
        msg = StreamMessage.from_json(raw)
        assert msg.type == StreamMessageType.ERROR
        assert msg.data["error"] == "oops"
        assert msg.id == ""

    def test_from_json_invalid_type_raises(self):
        raw = json.dumps({"type": "nonexistent", "data": {}})
        with pytest.raises(ValueError):
            StreamMessage.from_json(raw)


# ── Emit methods ────────────────────────────────────────────────────


class TestEmit:
    def test_emit_text(self, streams):
        handler, out, _ = streams
        handler.emit_text("hello world")
        line = out.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["type"] == "assistant_text"
        assert parsed["data"]["text"] == "hello world"

    def test_emit_tool_use(self, streams):
        handler, out, _ = streams
        handler.emit_tool_use("shell", {"cmd": "ls"}, tool_use_id="t1")
        parsed = json.loads(out.getvalue().strip())
        assert parsed["type"] == "tool_use"
        assert parsed["data"]["tool_name"] == "shell"
        assert parsed["data"]["arguments"] == {"cmd": "ls"}
        assert parsed["data"]["tool_use_id"] == "t1"

    def test_emit_error(self, streams):
        handler, out, _ = streams
        handler.emit_error("something broke")
        parsed = json.loads(out.getvalue().strip())
        assert parsed["type"] == "error"
        assert parsed["data"]["error"] == "something broke"

    def test_emit_complete(self, streams):
        handler, out, _ = streams
        handler.emit_complete("all done")
        parsed = json.loads(out.getvalue().strip())
        assert parsed["type"] == "complete"
        assert parsed["data"]["result"] == "all done"


# ── Start / stop ────────────────────────────────────────────────────


class TestStartStop:
    def test_start_stop_toggle(self, streams):
        handler, _, _ = streams
        assert handler.running is False
        handler.start()
        assert handler.running is True
        handler.stop()
        assert handler.running is False


# ── Async reading ───────────────────────────────────────────────────


class TestReadOne:
    async def test_read_one_parses_message(self):
        msg_line = json.dumps({"type": "user_message", "data": {"text": "hi"}, "id": "1"}) + "\n"
        inp = io.StringIO(msg_line)
        out = io.StringIO()
        handler = BidiStreamHandler(input_stream=inp, output_stream=out)
        result = await handler.read_one(timeout=2.0)
        assert result is not None
        assert result.type == StreamMessageType.USER_MESSAGE
        assert result.data["text"] == "hi"

    async def test_read_one_eof_returns_none(self):
        inp = io.StringIO("")
        out = io.StringIO()
        handler = BidiStreamHandler(input_stream=inp, output_stream=out)
        result = await handler.read_one(timeout=1.0)
        assert result is None

    async def test_read_one_invalid_json_returns_none(self):
        inp = io.StringIO("NOT JSON\n")
        out = io.StringIO()
        handler = BidiStreamHandler(input_stream=inp, output_stream=out)
        result = await handler.read_one(timeout=1.0)
        assert result is None


class TestReadMessages:
    async def test_read_multiple_messages(self):
        lines = ""
        for i in range(3):
            lines += json.dumps({"type": "user_message", "data": {"n": i}, "id": str(i)}) + "\n"
        inp = io.StringIO(lines)
        out = io.StringIO()
        handler = BidiStreamHandler(input_stream=inp, output_stream=out)
        handler.start()

        collected = []
        async for msg in handler.read_messages():
            collected.append(msg)
        assert len(collected) == 3
        assert collected[2].data["n"] == 2
