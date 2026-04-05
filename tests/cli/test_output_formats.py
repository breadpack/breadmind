"""Tests for headless output formats (text/json/stream-json)."""

from __future__ import annotations

import io
import json

from breadmind.cli.output_formats import OutputFormat, OutputFormatter, StreamEvent


class TestOutputFormat:
    def test_enum_values(self):
        assert OutputFormat.TEXT == "text"
        assert OutputFormat.JSON == "json"
        assert OutputFormat.STREAM_JSON == "stream-json"


class TestStreamEvent:
    def test_default_fields(self):
        event = StreamEvent(type="start")
        assert event.type == "start"
        assert isinstance(event.timestamp, float)
        assert event.data == {}


class TestTextFormat:
    def test_emit_text_writes_plain(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_text("hello world")
        assert buf.getvalue() == "hello world"

    def test_emit_tool_use_writes_bracket(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_tool_use("shell", {"cmd": "ls"})
        assert "[tool_use] shell" in buf.getvalue()

    def test_emit_tool_result_success(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_tool_result("shell", "done", success=True)
        assert "ok" in buf.getvalue()

    def test_emit_tool_result_failure(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_tool_result("shell", "fail", success=False)
        assert "error" in buf.getvalue()

    def test_emit_error(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_error("something broke")
        assert "ERROR: something broke" in buf.getvalue()

    def test_emit_complete(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.TEXT, stream=buf)
        fmt.emit_complete("final answer")
        assert "final answer" in buf.getvalue()


class TestJsonFormat:
    def test_json_output_on_complete(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.JSON, stream=buf)
        fmt.emit_start(session_id="s1")
        fmt.emit_text("hello")
        fmt.emit_complete("done", cost={"tokens": 100}, session_id="s1")

        output = json.loads(buf.getvalue())
        assert output["result"] == "done"
        assert output["cost"] == {"tokens": 100}
        assert output["session_id"] == "s1"
        assert len(output["events"]) == 3

    def test_json_no_output_before_complete(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.JSON, stream=buf)
        fmt.emit_text("hello")
        # Nothing written yet
        assert buf.getvalue() == ""


class TestStreamJsonFormat:
    def test_ndjson_lines(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.STREAM_JSON, stream=buf)
        fmt.emit_start(session_id="s1")
        fmt.emit_text("hello")

        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        assert e1["type"] == "start"
        e2 = json.loads(lines[1])
        assert e2["type"] == "text_delta"
        assert e2["data"]["text"] == "hello"

    def test_stream_tool_events(self):
        buf = io.StringIO()
        fmt = OutputFormatter(OutputFormat.STREAM_JSON, stream=buf)
        fmt.emit_tool_use("run", {"x": 1})
        fmt.emit_tool_result("run", "ok")

        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "tool_use"
        assert json.loads(lines[1])["type"] == "tool_result"


class TestEventsAccumulation:
    def test_events_property_returns_copy(self):
        fmt = OutputFormatter(OutputFormat.TEXT, stream=io.StringIO())
        fmt.emit_text("a")
        events = fmt.events
        assert len(events) == 1
        events.clear()
        assert len(fmt.events) == 1
