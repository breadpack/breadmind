import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.base import LLMMessage, ToolDefinition


@pytest.fixture
def claude_provider():
    return ClaudeProvider(api_key="test-key", default_model="claude-sonnet-4-6")


@pytest.mark.asyncio
async def test_claude_chat_text_response(claude_provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Hello from Claude")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

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
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=20)

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
