"""E2E: 멀티턴 + 도구 호출."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import (
    Message, LLMResponse, TokenUsage, AgentContext, PromptBlock,
    ToolCallRequest, ToolResult, ToolDefinition, ToolSchema,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyGuard


@pytest.mark.asyncio
async def test_tool_call_and_response():
    """User → LLM → tool call → tool result → LLM → final text."""
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        # Turn 1: LLM requests tool call
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "ls"})],
            usage=TokenUsage(50, 20), stop_reason="tool_use",
        ),
        # Turn 2: LLM gives final response
        LLMResponse(
            content="파일 목록:\n- config.yaml\n- main.py",
            tool_calls=[], usage=TokenUsage(80, 40), stop_reason="end_turn",
        ),
    ])

    prompt_builder = MagicMock()
    prompt_builder.build.return_value = [
        PromptBlock(section="identity", content="You are BreadMind.", cacheable=True, priority=1),
    ]

    tool_registry = MagicMock()
    tool_def = ToolDefinition(name="shell_exec", description="Execute shell", parameters={})
    tool_registry.get_schemas.return_value = [
        ToolSchema(name="shell_exec", deferred=False, definition=tool_def),
    ]
    tool_registry.execute = AsyncMock(return_value=ToolResult(
        success=True, output="config.yaml\nmain.py",
    ))

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto"),
        max_turns=5,
    )

    ctx = AgentContext(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("파일 목록 보여줘", ctx)

    assert "config.yaml" in resp.content
    assert resp.tool_calls_count == 1
    assert provider.chat.call_count == 2
    tool_registry.execute.assert_called_once()


@pytest.mark.asyncio
async def test_blocked_tool_continues():
    """Safety blocks a tool → LLM continues without it."""
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "rm -rf /"})],
            usage=TokenUsage(50, 20), stop_reason="tool_use",
        ),
        LLMResponse(
            content="That command is too dangerous.",
            tool_calls=[], usage=TokenUsage(30, 15), stop_reason="end_turn",
        ),
    ])

    prompt_builder = MagicMock()
    prompt_builder.build.return_value = [
        PromptBlock(section="identity", content="You are BreadMind.", cacheable=True, priority=1),
    ]

    tool_registry = MagicMock()
    tool_registry.get_schemas.return_value = []
    tool_registry.execute = AsyncMock()

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto", blocked_patterns=["rm -rf /"]),
        max_turns=5,
    )

    ctx = AgentContext(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete everything", ctx)

    assert "dangerous" in resp.content.lower()
    tool_registry.execute.assert_not_called()


@pytest.mark.asyncio
async def test_multi_tool_calls():
    """LLM requests multiple tools in one turn."""
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "date"}),
                ToolCallRequest(id="tc2", name="shell_exec", arguments={"command": "uptime"}),
            ],
            usage=TokenUsage(50, 20), stop_reason="tool_use",
        ),
        LLMResponse(
            content="System is running since yesterday.",
            tool_calls=[], usage=TokenUsage(30, 15), stop_reason="end_turn",
        ),
    ])

    prompt_builder = MagicMock()
    prompt_builder.build.return_value = [
        PromptBlock(section="identity", content="Bot.", cacheable=True, priority=1),
    ]

    tool_registry = MagicMock()
    tool_registry.get_schemas.return_value = []
    tool_registry.execute = AsyncMock(return_value=ToolResult(success=True, output="OK"))

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto"),
    )

    ctx = AgentContext(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("check system", ctx)

    assert resp.tool_calls_count == 2
    assert tool_registry.execute.call_count == 2
