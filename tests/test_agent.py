import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.core.agent import CoreAgent
from breadmind.llm.base import LLMResponse, LLMMessage, ToolCall, TokenUsage
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.core.safety import SafetyGuard
from breadmind.memory.working import WorkingMemory

@tool(description="Test tool")
async def _test_tool(input: str) -> str:
    return f"result: {input}"

# Override the name to match what tests expect
_test_tool._tool_definition.name = "test_tool"

@tool(description="Slow tool")
async def _slow_tool(input: str) -> str:
    await asyncio.sleep(100)
    return f"slow: {input}"

_slow_tool._tool_definition.name = "slow_tool"


def _make_response(content=None, tool_calls=None, input_tokens=10, output_tokens=5):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn" if not tool_calls else "tool_use",
    )


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(_test_tool)
    reg.register(_slow_tool)
    return reg


@pytest.fixture
def agent(registry):
    provider = AsyncMock()
    guard = SafetyGuard()
    return CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )


@pytest.fixture
def agent_with_memory(registry):
    provider = AsyncMock()
    guard = SafetyGuard()
    memory = WorkingMemory()
    return CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        working_memory=memory,
    )


@pytest.mark.asyncio
async def test_agent_text_response(agent):
    agent._provider.chat = AsyncMock(return_value=_make_response(content="Hello!"))
    result = await agent.handle_message("hi", user="test", channel="test")
    assert result == "Hello!"


@pytest.mark.asyncio
async def test_agent_tool_call_loop(agent):
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "hello"})],
            input_tokens=10, output_tokens=20,
        ),
        _make_response(content="Done! Result was: result: hello"),
    ])
    result = await agent.handle_message("use the tool", user="test", channel="test")
    assert "Done!" in result
    assert agent._provider.chat.call_count == 2


@pytest.mark.asyncio
async def test_agent_max_turns_limit(agent):
    agent._provider.chat = AsyncMock(return_value=_make_response(
        tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "loop"})],
    ))
    agent._max_turns = 3
    result = await agent.handle_message("loop forever", user="test", channel="test")
    assert "max" in result.lower() or agent._provider.chat.call_count == 3


# --- Multi-turn conversation with WorkingMemory ---

@pytest.mark.asyncio
async def test_multi_turn_conversation(agent_with_memory):
    agent = agent_with_memory

    # First turn
    agent._provider.chat = AsyncMock(return_value=_make_response(content="Hi there!"))
    result1 = await agent.handle_message("hello", user="alice", channel="general")
    assert result1 == "Hi there!"

    # Second turn — should include previous messages
    agent._provider.chat = AsyncMock(return_value=_make_response(content="You said hello before."))
    result2 = await agent.handle_message("what did I say?", user="alice", channel="general")
    assert result2 == "You said hello before."

    # Verify the second call included previous conversation context
    call_args = agent._provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
    # Should have: system + prev_user + prev_assistant + current_user
    assert len(messages) >= 4
    assert messages[0].role == "system"
    # Previous user message
    assert messages[1].role == "user"
    assert messages[1].content == "hello"
    # Previous assistant reply
    assert messages[2].role == "assistant"
    assert messages[2].content == "Hi there!"
    # Current user message
    assert messages[3].role == "user"
    assert messages[3].content == "what did I say?"


@pytest.mark.asyncio
async def test_stateless_without_memory(agent):
    """Without working_memory, each call is independent."""
    agent._provider.chat = AsyncMock(return_value=_make_response(content="First"))
    await agent.handle_message("hello", user="alice", channel="general")

    agent._provider.chat = AsyncMock(return_value=_make_response(content="Second"))
    await agent.handle_message("what did I say?", user="alice", channel="general")

    call_args = agent._provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    # Should only have system + user (no history)
    assert len(messages) == 2


# --- Timeout handling ---

@pytest.mark.asyncio
async def test_chat_timeout(agent):
    async def slow_chat(**kwargs):
        await asyncio.sleep(100)
        return _make_response(content="too slow")

    agent._provider.chat = slow_chat
    agent._chat_timeout = 0.1
    result = await agent.handle_message("hi", user="test", channel="test")
    assert result == "요청 시간이 초과되었습니다."


@pytest.mark.asyncio
async def test_tool_timeout(agent):
    agent._tool_timeout = 0.1
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="slow_tool", arguments={"input": "x"})],
        ),
        _make_response(content="Tool timed out."),
    ])
    result = await agent.handle_message("use slow tool", user="test", channel="test")
    # The agent should have continued after the timeout
    assert agent._provider.chat.call_count == 2
    # Check the tool result message sent to the LLM contains timeout info
    second_call_messages = agent._provider.chat.call_args.kwargs.get("messages") or agent._provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert any("timed out" in m.content.lower() for m in tool_msgs)


# --- Error handling ---

@pytest.mark.asyncio
async def test_provider_exception(agent):
    agent._provider.chat = AsyncMock(side_effect=RuntimeError("connection lost"))
    result = await agent.handle_message("hi", user="test", channel="test")
    assert result == "서비스 오류가 발생했습니다."


# --- Cooldown integration ---

@pytest.mark.asyncio
async def test_cooldown_blocks_tool(registry):
    provider = AsyncMock()
    guard = SafetyGuard()
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    # First call executes normally
    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "a"})],
        ),
        _make_response(content="done1"),
    ])
    await agent.handle_message("run tool", user="bob", channel="ops")

    # Second call — same tool should be in cooldown
    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc2", name="test_tool", arguments={"input": "b"})],
        ),
        _make_response(content="done2"),
    ])
    await agent.handle_message("run tool again", user="bob", channel="ops")

    # Check the second round's tool result mentions cooldown
    second_call_messages = provider.chat.call_args.kwargs.get("messages") or provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert any("cooldown" in m.content.lower() for m in tool_msgs)


# --- Token usage tracking ---

@pytest.mark.asyncio
async def test_token_usage_tracking(agent):
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
            input_tokens=100, output_tokens=50,
        ),
        _make_response(content="result", input_tokens=200, output_tokens=80),
    ])
    await agent.handle_message("test", user="test", channel="test")

    usage = agent.get_usage()
    assert usage["input_tokens"] == 300
    assert usage["output_tokens"] == 130


# --- Parallel tool execution ---

@pytest.mark.asyncio
async def test_parallel_tool_execution(registry):
    provider = AsyncMock()
    guard = SafetyGuard()
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    # Response with two tool calls at once
    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[
                ToolCall(id="tc1", name="test_tool", arguments={"input": "a"}),
                ToolCall(id="tc2", name="test_tool", arguments={"input": "b"}),
            ],
        ),
        _make_response(content="Both done."),
    ])

    result = await agent.handle_message("do both", user="test", channel="test")
    assert result == "Both done."

    # Check both tool results are in the messages
    second_call_messages = provider.chat.call_args.kwargs.get("messages") or provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    # First tool call may be in cooldown (since both are test_tool with same target).
    # At least one should have succeeded.
    assert len(tool_msgs) == 2
    assert any("result: a" in m.content for m in tool_msgs)


# --- Tool result includes success/failure prefix ---

@pytest.mark.asyncio
async def test_tool_result_success_prefix(agent):
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="ok"),
    ])
    await agent.handle_message("run", user="test", channel="test")

    second_call_messages = agent._provider.chat.call_args.kwargs.get("messages") or agent._provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert any("[success=True]" in m.content for m in tool_msgs)


@pytest.mark.asyncio
async def test_blocked_tool_result_prefix(registry):
    provider = AsyncMock()
    guard = SafetyGuard(blacklist={"test": ["test_tool"]})
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="blocked"),
    ])
    await agent.handle_message("run", user="test", channel="test")

    second_call_messages = provider.chat.call_args.kwargs.get("messages") or provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert any("[success=False]" in m.content for m in tool_msgs)
