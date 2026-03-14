import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.llm.ollama import OllamaProvider
from breadmind.llm.base import LLMMessage


@pytest.fixture
def ollama_provider():
    return OllamaProvider(
        base_url="http://localhost:11434", default_model="llama3"
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
