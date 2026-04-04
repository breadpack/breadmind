"""StreamEvent and handle_message_stream() tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import AsyncGenerator

from breadmind.plugins.builtin.agent_loop.message_loop import (
    MessageLoopAgent,
    StreamEvent,
)
from breadmind.core.protocols import (
    AgentContext,
    LLMResponse,
    PromptBlock,
    TokenUsage,
    ToolCallRequest,
    ToolResult,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------

class FakeProvider:
    """chat() 응답 시퀀스를 제어할 수 있는 가짜 provider."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._call_index = 0
        self._stream_chunks: list[str] | None = None

    def supports_feature(self, feature: str) -> bool:
        return False

    async def chat(
        self, messages: list[Any], tools: list[Any] | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        resp = self._responses[self._call_index]
        self._call_index += 1
        return resp

    async def chat_stream(
        self, messages: list[Any], tools: list[Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        if self._stream_chunks:
            for chunk in self._stream_chunks:
                yield chunk
        else:
            # 마지막 chat() 응답의 content를 chunk로 분할
            last = self._responses[self._call_index - 1]
            if last.content:
                for ch in last.content:
                    yield ch

    def set_stream_chunks(self, chunks: list[str]) -> None:
        self._stream_chunks = chunks


class FakePromptBuilder:
    def build(self, ctx: Any) -> list[PromptBlock]:
        return [PromptBlock(section="id", content="You are a test agent.", cacheable=True, priority=1)]


class FakeToolRegistry:
    def get_schemas(self, _filter=None) -> list:
        return []

    async def execute(self, call: Any, ctx: Any) -> ToolResult:
        return ToolResult(success=True, output=f"Result of {call.name}")

    async def execute_batch(self, calls: list, ctx: Any) -> list[ToolResult]:
        return [await self.execute(c, ctx) for c in calls]


class FakeSafetyGuard:
    def check(self, name: str, arguments: dict) -> Any:
        @dataclass
        class Verdict:
            allowed: bool = True
            needs_approval: bool = False
            reason: str = ""
        return Verdict()


# ---------------------------------------------------------------------------
# StreamEvent dataclass tests
# ---------------------------------------------------------------------------

def test_stream_event_creation():
    e = StreamEvent(type="text", data="hello")
    assert e.type == "text"
    assert e.data == "hello"


def test_stream_event_defaults():
    e = StreamEvent(type="done")
    assert e.data is None


# ---------------------------------------------------------------------------
# handle_message_stream tests
# ---------------------------------------------------------------------------

def _make_agent(responses: list[LLMResponse], stream_chunks: list[str] | None = None):
    provider = FakeProvider(responses)
    if stream_chunks:
        provider.set_stream_chunks(stream_chunks)
    return MessageLoopAgent(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_registry=FakeToolRegistry(),
        safety_guard=FakeSafetyGuard(),
        max_turns=5,
    )


def _ctx() -> AgentContext:
    return AgentContext(user="test", channel="test", session_id="s1")


async def test_simple_text_stream():
    """도구 호출 없는 단순 텍스트 → text + done 이벤트만."""
    agent = _make_agent(
        responses=[
            LLMResponse(
                content="Hello world",
                tool_calls=[],
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                stop_reason="end_turn",
            ),
        ],
        stream_chunks=["Hello", " ", "world"],
    )

    events = []
    async for event in agent.handle_message_stream("hi", _ctx()):
        events.append(event)

    types = [e.type for e in events]
    assert "text" in types
    assert types[-1] == "done"
    # text 이벤트의 data를 합치면 원본과 동일
    text = "".join(e.data for e in events if e.type == "text")
    assert text == "Hello world"


async def test_tool_call_then_text_stream():
    """도구 호출 후 텍스트 → tool_start + tool_end + text + done."""
    agent = _make_agent(
        responses=[
            # Turn 1: tool call
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="t1", name="shell", arguments={"cmd": "ls"}),
                ],
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                stop_reason="tool_use",
            ),
            # Turn 2: text response
            LLMResponse(
                content="Done!",
                tool_calls=[],
                usage=TokenUsage(input_tokens=15, output_tokens=3),
                stop_reason="end_turn",
            ),
        ],
        stream_chunks=["Done", "!"],
    )

    events = []
    async for event in agent.handle_message_stream("run ls", _ctx()):
        events.append(event)

    types = [e.type for e in events]
    assert "tool_start" in types
    assert "tool_end" in types
    assert "text" in types
    assert types[-1] == "done"

    # tool_start에 도구 이름이 포함
    ts = next(e for e in events if e.type == "tool_start")
    assert "shell" in ts.data["tools"]

    # done 이벤트에 토큰 정보 포함
    done = next(e for e in events if e.type == "done")
    assert done.data["tokens"] > 0
    assert done.data["tool_calls"] == 1


async def test_no_stream_support_fallback():
    """chat_stream이 없는 provider → 전체 응답 1회 text 이벤트."""

    class NoStreamProvider:
        def supports_feature(self, feature: str) -> bool:
            return False

        async def chat(self, messages, tools=None, think_budget=None):
            return LLMResponse(
                content="Full response",
                tool_calls=[],
                usage=TokenUsage(input_tokens=5, output_tokens=3),
                stop_reason="end_turn",
            )
        # chat_stream 없음

    agent = MessageLoopAgent(
        provider=NoStreamProvider(),
        prompt_builder=FakePromptBuilder(),
        tool_registry=FakeToolRegistry(),
        safety_guard=FakeSafetyGuard(),
        max_turns=5,
    )

    events = []
    async for event in agent.handle_message_stream("hello", _ctx()):
        events.append(event)

    text_events = [e for e in events if e.type == "text"]
    assert len(text_events) == 1
    assert text_events[0].data == "Full response"
    assert events[-1].type == "done"


async def test_stream_error_handling():
    """스트리밍 중 에러 → error 이벤트 yield."""

    class ErrorProvider:
        def supports_feature(self, feature: str) -> bool:
            return False

        async def chat(self, messages, tools=None, think_budget=None):
            raise RuntimeError("API down")

    agent = MessageLoopAgent(
        provider=ErrorProvider(),
        prompt_builder=FakePromptBuilder(),
        tool_registry=FakeToolRegistry(),
        safety_guard=FakeSafetyGuard(),
        max_turns=5,
    )

    events = []
    async for event in agent.handle_message_stream("hello", _ctx()):
        events.append(event)

    assert any(e.type == "error" for e in events)
    error_event = next(e for e in events if e.type == "error")
    assert "API down" in error_event.data
