import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.agent import CoreAgent
from breadmind.llm.base import LLMResponse, LLMMessage, ToolCall, TokenUsage
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.core.safety import SafetyGuard

@tool(description="Test tool")
async def _test_tool(input: str) -> str:
    return f"result: {input}"

# Override the name to match what tests expect
_test_tool._tool_definition.name = "test_tool"

@pytest.fixture
def agent():
    registry = ToolRegistry()
    registry.register(_test_tool)
    provider = AsyncMock()
    guard = SafetyGuard()
    return CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

@pytest.mark.asyncio
async def test_agent_text_response(agent):
    agent._provider.chat = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    result = await agent.handle_message("hi", user="test", channel="test")
    assert result == "Hello!"

@pytest.mark.asyncio
async def test_agent_tool_call_loop(agent):
    # First call returns tool_call, second call returns text
    agent._provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "hello"})],
            usage=TokenUsage(input_tokens=10, output_tokens=20),
            stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done! Result was: result: hello",
            tool_calls=[],
            usage=TokenUsage(input_tokens=30, output_tokens=10),
            stop_reason="end_turn",
        ),
    ])
    result = await agent.handle_message("use the tool", user="test", channel="test")
    assert "Done!" in result
    assert agent._provider.chat.call_count == 2

@pytest.mark.asyncio
async def test_agent_max_turns_limit(agent):
    # Always returns tool_call — should stop at max_turns
    agent._provider.chat = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "loop"})],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="tool_use",
    ))
    agent._max_turns = 3
    result = await agent.handle_message("loop forever", user="test", channel="test")
    assert "max" in result.lower() or agent._provider.chat.call_count == 3
