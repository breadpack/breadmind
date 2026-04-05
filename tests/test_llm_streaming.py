"""LLM provider chat_stream() tests (mock-based, no real API calls)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.llm.base import LLMMessage


# ---------------------------------------------------------------------------
# GeminiProvider.chat_stream
# ---------------------------------------------------------------------------

async def test_gemini_chat_stream_returns_async_generator():
    """GeminiProvider.chat_stream()이 AsyncGenerator를 반환하는지 확인."""
    from breadmind.llm.gemini import GeminiProvider

    provider = GeminiProvider(api_key="fake-key", default_model="gemini-2.5-flash")

    # SSE 응답 시뮬레이션
    sse_lines = (
        'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n'
        '\n'
        'data: {"candidates": [{"content": {"parts": [{"text": " world"}]}}]}\n'
        '\n'
        'data: [DONE]\n'
    )

    class FakeContent:
        def __init__(self, data: bytes):
            self._data = data
            self._sent = False

        async def iter_any(self):
            if not self._sent:
                self._sent = True
                yield self._data

    class FakeResponse:
        status = 200
        content = FakeContent(sse_lines.encode("utf-8"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FakeSession:
        def post(self, url, **kwargs):
            return FakeResponse()

        async def close(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    messages = [LLMMessage(role="user", content="hi")]

    with patch("aiohttp.ClientSession", return_value=FakeSession()):
        chunks = []
        async for chunk in provider.chat_stream(messages):
            chunks.append(chunk)

    assert chunks == ["Hello", " world"]


# ---------------------------------------------------------------------------
# GrokProvider.chat_stream
# ---------------------------------------------------------------------------

async def test_grok_chat_stream_returns_async_generator():
    """GrokProvider.chat_stream()이 AsyncGenerator를 반환하는지 확인."""
    from breadmind.llm.grok import GrokProvider

    provider = GrokProvider(api_key="fake-key", default_model="grok-3")

    # OpenAI 스트리밍 응답 시뮬레이션
    class FakeDelta:
        def __init__(self, content: str | None):
            self.content = content

    class FakeChoice:
        def __init__(self, delta: FakeDelta):
            self.delta = delta

    class FakeChunk:
        def __init__(self, content: str | None):
            self.choices = [FakeChoice(FakeDelta(content))]

    class FakeStream:
        def __init__(self):
            self._chunks = [
                FakeChunk("Hello"),
                FakeChunk(" "),
                FakeChunk("world"),
                FakeChunk(None),  # 마지막 청크 (빈 delta)
            ]
            self._index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._index >= len(self._chunks):
                raise StopAsyncIteration
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk

    # client.chat.completions.create를 mock
    provider._client = MagicMock()
    provider._client.chat.completions.create = AsyncMock(return_value=FakeStream())

    messages = [LLMMessage(role="user", content="hi")]
    chunks = []
    async for chunk in provider.chat_stream(messages):
        chunks.append(chunk)

    assert chunks == ["Hello", " ", "world"]


# ---------------------------------------------------------------------------
# OllamaProvider.chat_stream
# ---------------------------------------------------------------------------

async def test_ollama_chat_stream_returns_async_generator():
    """OllamaProvider.chat_stream()이 AsyncGenerator를 반환하는지 확인."""
    from breadmind.llm.ollama import OllamaProvider

    provider = OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

    # Ollama JSON line 응답 시뮬레이션
    json_lines = (
        json.dumps({"message": {"content": "Hello"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": " world"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": ""}, "done": True}) + "\n"
    )

    class FakeContent:
        def __init__(self, data: bytes):
            self._data = data
            self._sent = False

        async def iter_any(self):
            if not self._sent:
                self._sent = True
                yield self._data

    class FakeResponse:
        status = 200
        content = FakeContent(json_lines.encode("utf-8"))

        async def json(self):
            return {"message": {"content": "Hello world"}, "done": True}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FakeSession:
        def post(self, url, **kwargs):
            return FakeResponse()

        async def close(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    messages = [LLMMessage(role="user", content="hi")]

    with patch("aiohttp.ClientSession", return_value=FakeSession()):
        chunks = []
        async for chunk in provider.chat_stream(messages):
            chunks.append(chunk)

    assert chunks == ["Hello", " world"]


# ---------------------------------------------------------------------------
# Base LLMProvider.chat_stream fallback
# ---------------------------------------------------------------------------

async def test_base_chat_stream_fallback():
    """LLMProvider의 기본 chat_stream()이 chat()으로 폴백하는지 확인."""
    from breadmind.llm.base import LLMProvider, LLMResponse, TokenUsage

    class SimpleProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None, think_budget=None):
            return LLMResponse(
                content="Fallback response",
                tool_calls=[],
                usage=TokenUsage(input_tokens=5, output_tokens=3),
                stop_reason="end_turn",
            )

        async def health_check(self):
            return True

    provider = SimpleProvider()
    messages = [LLMMessage(role="user", content="hi")]
    chunks = []
    async for chunk in provider.chat_stream(messages):
        chunks.append(chunk)

    assert chunks == ["Fallback response"]
