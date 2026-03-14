import pytest
from breadmind.llm.base import (
    LLMResponse, ToolCall, TokenUsage, LLMMessage, LLMProvider, ToolDefinition,
)


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
