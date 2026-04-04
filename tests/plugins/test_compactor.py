import pytest
from unittest.mock import AsyncMock
from breadmind.core.protocols import Message, LLMResponse, TokenUsage
from breadmind.plugins.builtin.prompt_builder.compactor import LLMCompactor


@pytest.fixture
def provider():
    p = AsyncMock()
    p.chat = AsyncMock(return_value=LLMResponse(
        content="User asked about K8s pods. Agent listed 3 pods and restarted nginx.",
        tool_calls=[], usage=TokenUsage(50, 30), stop_reason="end_turn",
    ))
    return p


@pytest.mark.asyncio
async def test_compact_preserves_recent(provider):
    compactor = LLMCompactor(provider=provider, keep_recent=3)
    messages = [Message(role="user", content=f"msg-{i}") for i in range(8)]
    result = await compactor.compact(messages, budget_tokens=100)
    assert len(result.preserved) == 3
    assert result.preserved[0].content == "msg-5"
    assert "summary" in result.boundary.content.lower()


@pytest.mark.asyncio
async def test_compact_short_conversation(provider):
    compactor = LLMCompactor(provider=provider, keep_recent=5)
    messages = [Message(role="user", content="hi")]
    result = await compactor.compact(messages, budget_tokens=100)
    assert len(result.preserved) == 1
    assert result.tokens_saved == 0


@pytest.mark.asyncio
async def test_compact_tokens_saved(provider):
    compactor = LLMCompactor(provider=provider, keep_recent=2)
    messages = [Message(role="user", content="x" * 400) for _ in range(6)]
    result = await compactor.compact(messages, budget_tokens=100)
    assert result.tokens_saved > 0


@pytest.mark.asyncio
async def test_summarize_standalone(provider):
    compactor = LLMCompactor(provider=provider, keep_recent=3)
    messages = [Message(role="user", content="check pods"), Message(role="assistant", content="3 pods running")]
    summary = await compactor.summarize(messages)
    assert "K8s" in summary or "pods" in summary


@pytest.mark.asyncio
async def test_clean_long_messages(provider):
    compactor = LLMCompactor(provider=provider, keep_recent=1)
    messages = [
        Message(role="user", content="a" * 5000),
        Message(role="assistant", content="done"),
    ]
    result = await compactor.compact(messages, budget_tokens=100)
    assert len(result.preserved) == 1
