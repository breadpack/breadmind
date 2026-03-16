import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.memory.summarizer import ConversationSummarizer
from breadmind.llm.base import LLMMessage, LLMResponse, TokenUsage


@pytest.fixture
def mock_provider():
    p = AsyncMock()
    p.model_name = "claude-sonnet-4-6"
    p.chat = AsyncMock(return_value=LLMResponse(
        content="Summary of conversation",
        tool_calls=[],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        stop_reason="end_turn",
    ))
    return p


@pytest.mark.asyncio
async def test_no_summarize_when_under_limit(mock_provider):
    summarizer = ConversationSummarizer(mock_provider, keep_recent=5)
    msgs = [
        LLMMessage(role="system", content="You are helpful."),
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="assistant", content="Hi there!"),
    ]
    result = await summarizer.summarize_if_needed(msgs, None)
    assert result == msgs
    mock_provider.chat.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_when_many_messages(mock_provider):
    summarizer = ConversationSummarizer(mock_provider, keep_recent=3, target_ratio=0.0001)
    msgs = [LLMMessage(role="system", content="System prompt")]
    for i in range(20):
        msgs.append(LLMMessage(role="user", content=f"Message {i}" * 100))
        msgs.append(LLMMessage(role="assistant", content=f"Reply {i}" * 100))
    result = await summarizer.summarize_if_needed(msgs, None)
    # Should have: system + summary + last 3 messages
    assert len(result) < len(msgs)
    assert result[0].role == "system"
    assert "[Earlier conversation summary]" in result[1].content
