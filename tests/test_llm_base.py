import asyncio
import pytest
from breadmind.llm.base import (
    LLMResponse, ToolCall, TokenUsage, LLMMessage, LLMProvider, ToolDefinition,
    FallbackProvider, ConversationSummarizer,
)
from breadmind.llm.token_counter import TokenCounter
from breadmind.llm.rate_limiter import RateLimiter


def test_llm_response_with_text():
    resp = LLMResponse(
        content="Hello",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    assert resp.content == "Hello"
    assert resp.has_tool_calls is False


def test_llm_response_with_tool_call():
    tc = ToolCall(
        id="tc_1",
        name="k8s_list_pods",
        arguments={"namespace": "default"},
    )
    resp = LLMResponse(
        content=None,
        tool_calls=[tc],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="tool_use",
    )
    assert resp.has_tool_calls is True
    assert resp.tool_calls[0].name == "k8s_list_pods"


def test_llm_message_roles():
    msg = LLMMessage(role="user", content="hello")
    assert msg.role == "user"


def test_token_usage_total_tokens():
    """total_tokens 프로퍼티가 모든 토큰 필드의 합계를 반환하는지 확인한다."""
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=20,
        cache_read_input_tokens=30,
    )
    assert usage.total_tokens == 200


def test_token_usage_total_tokens_defaults():
    """캐시 토큰이 기본값(0)일 때 total_tokens가 정상 동작하는지 확인한다."""
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    assert usage.total_tokens == 15


def test_token_usage_cost_sonnet():
    """claude-sonnet-4-6 모델의 비용 계산이 정확한지 확인한다."""
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    cost = usage.cost("claude-sonnet-4-6")
    # input: 3.0 + output: 15.0 + cache_creation: 3.75 + cache_read: 0.30
    assert cost == pytest.approx(22.05)


def test_token_usage_cost_haiku():
    """claude-haiku-4-5 모델의 비용 계산이 정확한지 확인한다."""
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    cost = usage.cost("claude-haiku-4-5")
    # input: 0.80 + output: 4.0
    assert cost == pytest.approx(4.80)


def test_token_usage_cost_unknown_model():
    """지원되지 않는 모델에 대해 ValueError가 발생하는지 확인한다."""
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    with pytest.raises(ValueError, match="지원되지 않는 모델"):
        usage.cost("unknown-model")


@pytest.mark.asyncio
async def test_chat_stream_fallback():
    """chat_stream 기본 구현이 chat()으로 폴백하여 전체 응답을 반환하는지 확인한다."""

    class _TestProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None):
            return LLMResponse(
                content="전체 응답 텍스트",
                tool_calls=[],
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                stop_reason="end_turn",
            )

        async def health_check(self):
            return True

    provider = _TestProvider()
    chunks = []
    async for chunk in provider.chat_stream(
        messages=[LLMMessage(role="user", content="hi")]
    ):
        chunks.append(chunk)

    assert chunks == ["전체 응답 텍스트"]


@pytest.mark.asyncio
async def test_chat_stream_fallback_no_content():
    """chat_stream 기본 구현에서 content가 None이면 아무것도 반환하지 않는지 확인한다."""

    class _TestProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None):
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="1", name="test", arguments={})],
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                stop_reason="tool_use",
            )

        async def health_check(self):
            return True

    provider = _TestProvider()
    chunks = []
    async for chunk in provider.chat_stream(
        messages=[LLMMessage(role="user", content="hi")]
    ):
        chunks.append(chunk)

    assert chunks == []


# --- FallbackProvider tests ---


class _SuccessProvider(LLMProvider):
    def __init__(self, content: str = "ok"):
        self._content = content

    async def chat(self, messages, tools=None, model=None):
        return LLMResponse(
            content=self._content,
            tool_calls=[],
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )

    async def health_check(self):
        return True


class _FailProvider(LLMProvider):
    async def chat(self, messages, tools=None, model=None):
        raise ConnectionError("provider down")

    async def health_check(self):
        return False


@pytest.mark.asyncio
async def test_fallback_provider_succeeds_with_first():
    """FallbackProvider가 첫 번째 프로바이더 성공 시 바로 반환하는지 확인한다."""
    fb = FallbackProvider([_SuccessProvider("first"), _SuccessProvider("second")])
    result = await fb.chat([LLMMessage(role="user", content="hi")])
    assert result.content == "first"


@pytest.mark.asyncio
async def test_fallback_provider_tries_second_on_failure():
    """FallbackProvider가 첫 번째 실패 시 두 번째를 시도하는지 확인한다."""
    fb = FallbackProvider([_FailProvider(), _SuccessProvider("second")])
    result = await fb.chat([LLMMessage(role="user", content="hi")])
    assert result.content == "second"


@pytest.mark.asyncio
async def test_fallback_provider_all_fail():
    """모든 프로바이더 실패 시 마지막 에러를 발생시키는지 확인한다."""
    fb = FallbackProvider([_FailProvider(), _FailProvider()])
    with pytest.raises(ConnectionError):
        await fb.chat([LLMMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_fallback_provider_health_check():
    """health_check가 하나라도 성공하면 True를 반환하는지 확인한다."""
    fb = FallbackProvider([_FailProvider(), _SuccessProvider()])
    assert await fb.health_check() is True


@pytest.mark.asyncio
async def test_fallback_provider_health_check_all_fail():
    """모든 프로바이더가 다운되면 health_check가 False를 반환하는지 확인한다."""
    fb = FallbackProvider([_FailProvider(), _FailProvider()])
    assert await fb.health_check() is False


# --- ConversationSummarizer tests ---


@pytest.mark.asyncio
async def test_summarizer_no_summarization_needed():
    """임계값 이하일 때 메시지가 그대로 반환되는지 확인한다."""
    provider = _SuccessProvider()
    tc = TokenCounter()
    summarizer = ConversationSummarizer(provider, tc)

    messages = [
        LLMMessage(role="system", content="You are helpful."),
        LLMMessage(role="user", content="Hello"),
    ]
    result = await summarizer.summarize_if_needed(messages, "claude-sonnet-4-6")
    assert result == messages


@pytest.mark.asyncio
async def test_summarizer_triggers_when_over_threshold():
    """임계값 초과 시 요약이 수행되는지 확인한다."""

    class _SummaryProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None):
            return LLMResponse(
                content="Summary of conversation",
                tool_calls=[],
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                stop_reason="end_turn",
            )

        async def health_check(self):
            return True

    provider = _SummaryProvider()
    tc = TokenCounter()
    summarizer = ConversationSummarizer(provider, tc)

    # Create many messages to exceed threshold
    messages = [LLMMessage(role="system", content="System prompt.")]
    for i in range(100):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(LLMMessage(role=role, content=f"Message {i} " * 200))

    # Use a very low threshold to force summarization
    result = await summarizer.summarize_if_needed(
        messages, "claude-sonnet-4-6", threshold_ratio=0.0001
    )

    # Should have: system + summary + last 10 messages
    assert result[0].role == "system"
    assert result[0].content == "System prompt."
    assert result[1].role == "system"
    assert "Summary of conversation" in result[1].content
    assert len(result) == 12  # system + summary + 10 tail


@pytest.mark.asyncio
async def test_summarizer_preserves_system_and_recent():
    """요약 시 시스템 메시지와 최근 메시지가 보존되는지 확인한다."""

    class _SummaryProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None):
            return LLMResponse(
                content="Condensed summary",
                tool_calls=[],
                usage=TokenUsage(input_tokens=5, output_tokens=5),
                stop_reason="end_turn",
            )

        async def health_check(self):
            return True

    provider = _SummaryProvider()
    tc = TokenCounter()
    summarizer = ConversationSummarizer(provider, tc)

    messages = [LLMMessage(role="system", content="Be helpful.")]
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(LLMMessage(role=role, content=f"Msg {i} " * 100))

    result = await summarizer.summarize_if_needed(
        messages, "claude-sonnet-4-6", threshold_ratio=0.0001
    )

    # First message is original system
    assert result[0].content == "Be helpful."
    # Second is summary
    assert "Condensed summary" in result[1].content
    # Last messages preserved
    assert result[-1].content == messages[-1].content
    assert result[-2].content == messages[-2].content


# --- TokenCounter tests ---


def test_token_counter_estimate_english():
    """영어 텍스트의 토큰 수 추정이 올바른지 확인한다."""
    text = "Hello world"  # 11 chars -> 11/4 = 2.75 -> 2 (but min 1)
    tokens = TokenCounter.estimate_tokens(text)
    assert tokens == int(11 / 4)


def test_token_counter_estimate_cjk():
    """CJK 텍스트의 토큰 수 추정이 올바른지 확인한다."""
    text = "안녕하세요"  # 5 CJK chars -> 5/2 = 2.5 -> 2
    tokens = TokenCounter.estimate_tokens(text)
    assert tokens == int(5 / 2)


def test_token_counter_estimate_mixed():
    """영어와 CJK 혼합 텍스트의 토큰 수 추정이 올바른지 확인한다."""
    text = "Hello 세계"  # 6 non-CJK + 2 CJK
    tokens = TokenCounter.estimate_tokens(text)
    expected = int(6 / 4 + 2 / 2)  # 1 + 1 = 2
    assert tokens == expected


def test_token_counter_estimate_empty():
    """빈 텍스트의 토큰 수가 0인지 확인한다."""
    assert TokenCounter.estimate_tokens("") == 0


def test_token_counter_fits_in_context():
    """메시지가 컨텍스트 윈도우에 맞는지 확인한다."""
    messages = [LLMMessage(role="user", content="short message")]
    assert TokenCounter.fits_in_context(messages, None, "claude-sonnet-4-6") is True


def test_token_counter_fits_in_context_with_tools():
    """도구 정의 포함 시 컨텍스트 윈도우 확인이 올바른지 확인한다."""
    messages = [LLMMessage(role="user", content="hi")]
    tools = [ToolDefinition(name="test", description="A test tool", parameters={"type": "object"})]
    assert TokenCounter.fits_in_context(messages, tools, "claude-sonnet-4-6") is True


def test_token_counter_trim_messages_preserves_system_and_last():
    """trim_messages_to_fit이 시스템 메시지와 마지막 메시지를 보존하는지 확인한다."""
    messages = [
        LLMMessage(role="system", content="System"),
        LLMMessage(role="user", content="First user msg " * 50000),
        LLMMessage(role="assistant", content="First assistant msg " * 50000),
        LLMMessage(role="user", content="Last user msg"),
    ]
    # Use a tiny model limit to force trimming
    result = TokenCounter.trim_messages_to_fit(messages, None, "claude-sonnet-4-6", reserve=199_990)
    # System and last message must be preserved
    assert result[0].role == "system"
    assert result[0].content == "System"
    assert result[-1].content == "Last user msg"


def test_token_counter_trim_no_trimming_needed():
    """트리밍이 필요 없을 때 원본 메시지가 반환되는지 확인한다."""
    messages = [
        LLMMessage(role="system", content="System"),
        LLMMessage(role="user", content="Hello"),
    ]
    result = TokenCounter.trim_messages_to_fit(messages, None, "claude-sonnet-4-6")
    assert len(result) == 2


def test_token_counter_get_model_limit():
    """알려진 모델의 컨텍스트 윈도우 크기가 올바른지 확인한다."""
    assert TokenCounter.get_model_limit("claude-sonnet-4-6") == 200_000
    assert TokenCounter.get_model_limit("claude-opus-4-6") == 1_000_000
    # Unknown model returns default
    assert TokenCounter.get_model_limit("unknown") == 200_000


def test_token_counter_estimate_messages_tokens():
    """메시지 리스트의 토큰 수 추정이 올바른지 확인한다."""
    messages = [
        LLMMessage(role="system", content="Be helpful."),
        LLMMessage(role="user", content="Hello"),
    ]
    tokens = TokenCounter.estimate_messages_tokens(messages)
    assert tokens > 0


def test_token_counter_estimate_tools_tokens():
    """도구 정의의 토큰 수 추정이 올바른지 확인한다."""
    tools = [
        ToolDefinition(name="test_tool", description="A test tool", parameters={"type": "object"}),
    ]
    tokens = TokenCounter.estimate_tools_tokens(tools)
    assert tokens > 0


# --- RateLimiter tests ---


@pytest.mark.asyncio
async def test_rate_limiter_acquire_basic():
    """기본 acquire가 차단 없이 성공하는지 확인한다."""
    limiter = RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=10000)
    await limiter.acquire(100)
    stats = limiter.get_usage_stats()
    assert stats["requests_per_minute"] == 1
    assert stats["tokens_per_minute"] == 100


@pytest.mark.asyncio
async def test_rate_limiter_record_usage():
    """record_usage가 토큰 사용량을 올바르게 기록하는지 확인한다."""
    limiter = RateLimiter(max_requests_per_minute=10, max_tokens_per_minute=10000)
    await limiter.record_usage(500)
    stats = limiter.get_usage_stats()
    assert stats["tokens_per_minute"] == 500


@pytest.mark.asyncio
async def test_rate_limiter_stats():
    """get_usage_stats가 올바른 남은 용량을 반환하는지 확인한다."""
    limiter = RateLimiter(max_requests_per_minute=60, max_tokens_per_minute=100_000)
    await limiter.acquire(1000)
    stats = limiter.get_usage_stats()
    assert stats["remaining_rpm"] == 59
    assert stats["remaining_tpm"] == 99_000
    assert stats["max_rpm"] == 60
    assert stats["max_tpm"] == 100_000


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_limit_exceeded():
    """RPM 제한 초과 시 acquire가 대기하는지 확인한다."""
    limiter = RateLimiter(max_requests_per_minute=2, max_tokens_per_minute=100_000)

    # Use up the limit
    await limiter.acquire(10)
    await limiter.acquire(10)

    # Third acquire should block (we test with a timeout)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(10), timeout=0.5)


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_tpm_exceeded():
    """TPM 제한 초과 시 acquire가 대기하는지 확인한다."""
    limiter = RateLimiter(max_requests_per_minute=100, max_tokens_per_minute=100)

    await limiter.acquire(90)

    # Next request would exceed TPM limit
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(50), timeout=0.5)
