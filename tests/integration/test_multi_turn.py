"""E2E: 멀티턴 + 도구 호출."""
import pytest
from unittest.mock import AsyncMock

from breadmind.core.protocols import (
    LLMResponse, TokenUsage, ToolCallRequest, ToolResult,
    ToolDefinition, ToolSchema,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyGuard

from tests.factories import (
    make_agent_context,
    make_mock_prompt_builder,
    make_mock_provider,
    make_mock_tool_registry,
    make_text_response,
    make_tool_call_response,
    make_tool_result,
)


@pytest.mark.asyncio
async def test_tool_call_and_response():
    """User → LLM → tool call → tool result → LLM → final text."""
    tool_call_resp = make_tool_call_response(
        [("tc1", "shell_exec", {"command": "ls"})],
    )
    final_resp = make_text_response(
        "파일 목록:\n- config.yaml\n- main.py",
        usage=TokenUsage(80, 40),
    )
    provider = make_mock_provider([tool_call_resp, final_resp])

    prompt_builder = make_mock_prompt_builder()

    tool_def = ToolDefinition(name="shell_exec", description="Execute shell", parameters={})
    tool_result = make_tool_result("config.yaml\nmain.py")
    tool_registry = make_mock_tool_registry(
        schemas=[ToolSchema(name="shell_exec", deferred=False, definition=tool_def)],
        results=[tool_result],
    )

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto"),
        max_turns=5,
    )

    ctx = make_agent_context(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("파일 목록 보여줘", ctx)

    assert "config.yaml" in resp.content
    assert resp.tool_calls_count == 1
    assert provider.chat.call_count == 2
    tool_registry.execute_batch.assert_called_once()


@pytest.mark.asyncio
async def test_blocked_tool_continues():
    """Safety blocks a tool → LLM continues without it."""
    provider = make_mock_provider([
        make_tool_call_response(
            [("tc1", "shell_exec", {"command": "rm -rf /"})],
        ),
        make_text_response("That command is too dangerous.",
                           usage=TokenUsage(30, 15)),
    ])

    prompt_builder = make_mock_prompt_builder()
    tool_registry = make_mock_tool_registry()

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto", blocked_patterns=["rm -rf /"]),
        max_turns=5,
    )

    ctx = make_agent_context(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete everything", ctx)

    assert "dangerous" in resp.content.lower()
    tool_registry.execute.assert_not_called()


@pytest.mark.asyncio
async def test_multi_tool_calls():
    """LLM requests multiple tools in one turn."""
    provider = make_mock_provider([
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "date"}),
                ToolCallRequest(id="tc2", name="shell_exec", arguments={"command": "uptime"}),
            ],
            usage=TokenUsage(50, 20), stop_reason="tool_use",
        ),
        make_text_response("System is running since yesterday.",
                           usage=TokenUsage(30, 15)),
    ])

    prompt_builder = make_mock_prompt_builder()

    tool_result = make_tool_result()
    tool_registry = make_mock_tool_registry(results=[tool_result, tool_result])

    agent = MessageLoopAgent(
        provider=provider, prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=SafetyGuard(autonomy="auto"),
    )

    ctx = make_agent_context(user="admin", channel="cli", session_id="s1")
    resp = await agent.handle_message("check system", ctx)

    assert resp.tool_calls_count == 2
    assert tool_registry.execute_batch.call_count == 1
