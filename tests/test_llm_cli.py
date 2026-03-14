import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.llm.cli import CLIProvider
from breadmind.llm.base import LLMMessage


@pytest.fixture
def cli_provider():
    return CLIProvider(command="claude", args=["-p"], name="claude-cli")


@pytest.mark.asyncio
async def test_cli_provider_text_response(cli_provider):
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"Hello from CLI", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await cli_provider.chat(
            messages=[LLMMessage(role="user", content="hi")]
        )
    assert result.content == "Hello from CLI"
    assert result.has_tool_calls is False
