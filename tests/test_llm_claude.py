import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.base import LLMMessage, ToolDefinition
from breadmind.llm.rate_limiter import RateLimiter


@pytest.fixture
def claude_provider():
    return ClaudeProvider(api_key="test-key", default_model="claude-sonnet-4-6")


@pytest.fixture
def claude_provider_with_limiter():
    limiter = RateLimiter(max_requests_per_minute=60, max_tokens_per_minute=100_000)
    return ClaudeProvider(
        api_key="test-key",
        default_model="claude-sonnet-4-6",
        rate_limiter=limiter,
    )


@pytest.mark.asyncio
async def test_claude_chat_text_response(claude_provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Hello from Claude")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="hi")],
        )
    assert result.content == "Hello from Claude"
    assert result.has_tool_calls is False


@pytest.mark.asyncio
async def test_claude_chat_tool_call(claude_provider):
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tc_1"
    tool_block.name = "k8s_list_pods"
    tool_block.input = {"namespace": "default"}

    mock_response = MagicMock()
    mock_response.content = [tool_block]
    mock_response.stop_reason = "tool_use"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=20,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        tool_def = ToolDefinition(
            name="k8s_list_pods",
            description="List pods",
            parameters={"type": "object", "properties": {}},
        )
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="list pods")],
            tools=[tool_def],
        )
    assert result.has_tool_calls is True
    assert result.tool_calls[0].name == "k8s_list_pods"


@pytest.mark.asyncio
async def test_claude_system_prompt_passed_to_api(claude_provider):
    """시스템 프롬프트가 system 파라미터로 올바르게 전달되는지 확인한다."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="응답")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_create:
        await claude_provider.chat(
            messages=[
                LLMMessage(role="system", content="당신은 인프라 전문가입니다."),
                LLMMessage(role="user", content="hello"),
            ],
        )

    call_kwargs = mock_create.call_args[1]
    # system 파라미터가 전달되었는지 확인
    assert "system" in call_kwargs
    system_blocks = call_kwargs["system"]
    assert len(system_blocks) == 1
    assert system_blocks[0]["type"] == "text"
    assert system_blocks[0]["text"] == "당신은 인프라 전문가입니다."
    # 캐시 제어가 포함되었는지 확인
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
    # messages에 system 메시지가 포함되지 않았는지 확인
    api_messages = call_kwargs["messages"]
    for m in api_messages:
        assert m["role"] != "system"


@pytest.mark.asyncio
async def test_claude_cache_control_on_tools(claude_provider):
    """도구 목록의 마지막 도구에 cache_control이 포함되는지 확인한다."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="응답")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_create:
        tools = [
            ToolDefinition(name="tool_a", description="A", parameters={}),
            ToolDefinition(name="tool_b", description="B", parameters={}),
        ]
        await claude_provider.chat(
            messages=[LLMMessage(role="user", content="test")],
            tools=tools,
        )

    call_kwargs = mock_create.call_args[1]
    api_tools = call_kwargs["tools"]
    # 첫 번째 도구에는 cache_control이 없어야 한다
    assert "cache_control" not in api_tools[0]
    # 마지막 도구에 cache_control이 있어야 한다
    assert api_tools[-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_claude_parse_cache_tokens(claude_provider):
    """응답에서 캐시 토큰 정보가 올바르게 파싱되는지 확인한다."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="응답")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=30,
        cache_read_input_tokens=70,
    )

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="test")],
        )

    assert result.usage.cache_creation_input_tokens == 30
    assert result.usage.cache_read_input_tokens == 70
    assert result.usage.total_tokens == 250


@pytest.mark.asyncio
async def test_claude_health_check(claude_provider):
    """health_check가 API 호출 없이 키 존재 여부만 확인하는지 검증한다."""
    result = await claude_provider.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_claude_health_check_no_key():
    """API 키가 비어있을 때 health_check가 False를 반환하는지 확인한다."""
    provider = ClaudeProvider(api_key="")
    result = await provider.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_claude_with_rate_limiter(claude_provider_with_limiter):
    """rate_limiter가 설정된 ClaudeProvider가 정상 동작하는지 확인한다."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="response")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    with patch.object(
        claude_provider_with_limiter._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await claude_provider_with_limiter.chat(
            messages=[LLMMessage(role="user", content="hello")],
        )

    assert result.content == "response"
    stats = claude_provider_with_limiter._rate_limiter.get_usage_stats()
    assert stats["requests_per_minute"] >= 1
    assert stats["tokens_per_minute"] > 0


@pytest.mark.asyncio
async def test_claude_retry_on_rate_limit(claude_provider):
    """429 RateLimitError 시 재시도하는지 확인한다."""
    import anthropic

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="retry success")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    rate_limit_error = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}, json=MagicMock(return_value={})),
        body=None,
    )

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise rate_limit_error
        return mock_response

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ), patch("breadmind.llm.claude.asyncio.sleep", new_callable=AsyncMock):
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="hi")],
        )

    assert result.content == "retry success"
    assert call_count == 3
