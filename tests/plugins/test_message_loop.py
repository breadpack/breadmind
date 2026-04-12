import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import (
    Message, LLMResponse, TokenUsage, AgentContext, PromptBlock, ToolCallRequest, ToolResult,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyVerdict

@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.supports_feature.return_value = False
    provider.transform_system_prompt.side_effect = lambda blocks: blocks
    provider.transform_messages.side_effect = lambda msgs: msgs
    provider.fallback = None
    return provider

@pytest.fixture
def mock_prompt_builder():
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0),
    ]
    builder.inject_reminder.side_effect = lambda k, c: Message(role="user", content=c, is_meta=True)
    return builder

@pytest.fixture
def mock_tool_registry():
    registry = MagicMock()
    registry.get_schemas.return_value = []
    registry.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    registry.execute_batch = AsyncMock(return_value=[ToolResult(success=True, output="done")])
    return registry

@pytest.fixture
def mock_safety():
    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)
    return guard

@pytest.fixture
def agent(mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety):
    return MessageLoopAgent(
        provider=mock_provider, prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry, safety_guard=mock_safety, max_turns=5,
    )

@pytest.mark.asyncio
async def test_simple_text_response(agent, mock_provider):
    mock_provider.chat.return_value = LLMResponse(
        content="Hello!", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
    )
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("hi", ctx)
    assert resp.content == "Hello!"
    assert resp.tool_calls_count == 0

@pytest.mark.asyncio
async def test_tool_call_then_response(agent, mock_provider, mock_tool_registry):
    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "ls"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Files listed.", tool_calls=[], usage=TokenUsage(20, 10), stop_reason="end_turn",
        ),
    ]
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("list files", ctx)
    assert resp.content == "Files listed."
    assert resp.tool_calls_count == 1
    mock_tool_registry.execute_batch.assert_called_once()

@pytest.mark.asyncio
async def test_max_turns_limit(agent, mock_provider):
    mock_provider.chat.return_value = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={})],
        usage=TokenUsage(10, 5), stop_reason="tool_use",
    )
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("loop", ctx)
    assert mock_provider.chat.call_count == 5  # max_turns
    assert resp.content == "Max turns reached."
