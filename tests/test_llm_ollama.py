import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.llm.ollama import OllamaProvider
from breadmind.llm.base import LLMMessage
from breadmind.llm.rate_limiter import RateLimiter


@pytest.fixture
def ollama_provider():
    return OllamaProvider(
        base_url="http://localhost:11434", default_model="llama3"
    )


@pytest.fixture
def ollama_provider_with_limiter():
    limiter = RateLimiter(max_requests_per_minute=60, max_tokens_per_minute=100_000)
    return OllamaProvider(
        base_url="http://localhost:11434",
        default_model="llama3",
        rate_limiter=limiter,
    )


@pytest.mark.asyncio
async def test_ollama_chat(ollama_provider):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Hello"},
        "done": True,
        "eval_count": 5,
        "prompt_eval_count": 10,
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await ollama_provider.chat(
            messages=[LLMMessage(role="user", content="hi")]
        )
    assert result.content == "Hello"
    assert result.has_tool_calls is False


@pytest.mark.asyncio
async def test_ollama_health_check_success():
    """헬스체크 성공 시 True를 반환하는지 확인한다."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        provider = OllamaProvider()
        result = await provider.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_ollama_health_check_timeout():
    """서버 연결 실패 시 False를 반환하는지 확인한다."""
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        provider = OllamaProvider()
        result = await provider.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_ollama_with_rate_limiter(ollama_provider_with_limiter):
    """rate_limiter가 설정된 OllamaProvider가 정상 동작하는지 확인한다."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Hello"},
        "done": True,
        "eval_count": 5,
        "prompt_eval_count": 10,
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await ollama_provider_with_limiter.chat(
            messages=[LLMMessage(role="user", content="hi")]
        )

    assert result.content == "Hello"
    stats = ollama_provider_with_limiter._rate_limiter.get_usage_stats()
    assert stats["requests_per_minute"] >= 1
    assert stats["tokens_per_minute"] > 0
