"""E2E: 단일 턴 대화."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import (
    LLMResponse, TokenUsage, AgentContext, PromptBlock,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyGuard


@pytest.mark.asyncio
async def test_single_turn_text_response():
    """System prompt → LLM → text response."""
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="안녕하세요! BreadMind입니다.",
        tool_calls=[], usage=TokenUsage(100, 50), stop_reason="end_turn",
    ))

    prompt_builder = MagicMock()
    prompt_builder.build.return_value = [
        PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0),
        PromptBlock(section="identity", content="You are BreadMind.", cacheable=True, priority=1),
    ]

    tool_registry = MagicMock()
    tool_registry.get_schemas.return_value = []

    agent = MessageLoopAgent(
        provider=provider,
        prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto"),
    )

    ctx = AgentContext(user="admin", channel="web", session_id="s1")
    resp = await agent.handle_message("안녕하세요", ctx)

    assert "BreadMind" in resp.content
    assert resp.tool_calls_count == 0
    assert resp.tokens_used == 150
    provider.chat.assert_called_once()


@pytest.mark.asyncio
async def test_single_turn_with_sdk_agent():
    """SDK Agent.run() → single turn response."""
    from breadmind.sdk.agent import Agent

    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="Hello from SDK!", tool_calls=[],
        usage=TokenUsage(10, 5), stop_reason="end_turn",
    ))

    agent = Agent(name="TestBot", plugins={"provider": provider})
    result = await agent.run("hello")
    assert result == "Hello from SDK!"
