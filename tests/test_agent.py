import asyncio
import json
import logging
import pytest
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.core.agent import CoreAgent
from breadmind.llm.base import LLMResponse, LLMMessage, ToolCall, TokenUsage
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.core.safety import SafetyGuard
from breadmind.core.audit import AuditLogger, AuditEntry
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


@pytest.fixture
def audit_logger():
    return AuditLogger()


@pytest.fixture
def agent_with_audit(registry, audit_logger):
    provider = AsyncMock()
    guard = SafetyGuard()
    return CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        audit_logger=audit_logger,
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


# --- AuditLogger tests ---

def test_audit_log_tool_call(audit_logger):
    entry = audit_logger.log_tool_call(
        user="alice", channel="ops", tool_name="kubectl",
        arguments={"cmd": "get pods"}, result="pod list output",
        success=True, duration_ms=150.5,
    )
    assert entry.event_type == "tool_call"
    assert entry.result == "success"
    assert entry.details["tool_name"] == "kubectl"
    assert entry.details["duration_ms"] == 150.5
    assert entry.user == "alice"


def test_audit_log_safety_check(audit_logger):
    entry = audit_logger.log_safety_check(
        user="bob", channel="general", action="dangerous_action",
        safety_result="DENIED", reason="blacklisted",
    )
    assert entry.event_type == "safety_check"
    assert entry.result == "denied"
    assert entry.details["action"] == "dangerous_action"
    assert entry.details["reason"] == "blacklisted"


def test_audit_log_llm_call(audit_logger):
    entry = audit_logger.log_llm_call(
        user="alice", channel="ops", model="claude-sonnet-4-6",
        input_tokens=100, output_tokens=50, cache_hit=True,
        duration_ms=500.0,
    )
    assert entry.event_type == "llm_call"
    assert entry.result == "success"
    assert entry.details["model"] == "claude-sonnet-4-6"
    assert entry.details["input_tokens"] == 100
    assert entry.details["cache_hit"] is True


def test_audit_get_recent(audit_logger):
    for i in range(10):
        audit_logger.log_tool_call(
            user="u", channel="c", tool_name=f"tool_{i}",
            arguments={}, result="ok", success=True, duration_ms=10,
        )
    recent = audit_logger.get_recent(limit=5)
    assert len(recent) == 5
    # Should be the most recent 5
    assert recent[0].details["tool_name"] == "tool_5"
    assert recent[4].details["tool_name"] == "tool_9"


def test_audit_get_recent_all(audit_logger):
    for i in range(3):
        audit_logger.log_tool_call(
            user="u", channel="c", tool_name=f"tool_{i}",
            arguments={}, result="ok", success=True, duration_ms=10,
        )
    recent = audit_logger.get_recent(limit=50)
    assert len(recent) == 3


def test_audit_entry_has_timezone_aware_timestamp(audit_logger):
    entry = audit_logger.log_tool_call(
        user="u", channel="c", tool_name="t",
        arguments={}, result="ok", success=True, duration_ms=10,
    )
    # Timestamp should contain timezone info (ends with +00:00 or Z)
    assert "+" in entry.timestamp or "Z" in entry.timestamp


# --- Approval workflow tests ---

@pytest.mark.asyncio
async def test_approval_pending_created(registry):
    provider = AsyncMock()
    guard = SafetyGuard(require_approval=["test_tool"])
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="Awaiting approval."),
    ])
    await agent.handle_message("run tool", user="alice", channel="ops")

    pending = agent.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["tool"] == "test_tool"
    assert pending[0]["status"] == "pending"
    assert pending[0]["user"] == "alice"


@pytest.mark.asyncio
async def test_approval_approve_executes_tool(registry):
    provider = AsyncMock()
    guard = SafetyGuard(require_approval=["test_tool"])
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "hello"})],
        ),
        _make_response(content="Awaiting approval."),
    ])
    await agent.handle_message("run tool", user="alice", channel="ops")

    pending = agent.get_pending_approvals()
    approval_id = pending[0]["approval_id"]

    result = await agent.approve_tool(approval_id)
    assert result.success is True
    assert "result: hello" in result.output

    # Should no longer be pending
    assert len(agent.get_pending_approvals()) == 0


@pytest.mark.asyncio
async def test_approval_deny_removes_pending(registry):
    provider = AsyncMock()
    guard = SafetyGuard(require_approval=["test_tool"])
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="Awaiting approval."),
    ])
    await agent.handle_message("run tool", user="alice", channel="ops")

    pending = agent.get_pending_approvals()
    approval_id = pending[0]["approval_id"]

    agent.deny_tool(approval_id)
    assert len(agent.get_pending_approvals()) == 0


@pytest.mark.asyncio
async def test_approval_message_contains_approval_id(registry):
    provider = AsyncMock()
    guard = SafetyGuard(require_approval=["test_tool"])
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="Awaiting approval."),
    ])
    await agent.handle_message("run tool", user="alice", channel="ops")

    # Check the tool message sent to LLM includes approval_required and ID
    second_call_messages = provider.chat.call_args.kwargs.get("messages") or provider.chat.call_args[0][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert any("[approval_required]" in m.content for m in tool_msgs)
    # The approval ID should be in the message
    pending = agent.get_pending_approvals()
    approval_id = pending[0]["approval_id"]
    assert any(approval_id in m.content for m in tool_msgs)


# --- Structured logging tests ---

@pytest.mark.asyncio
async def test_structured_logging_llm_call(agent, caplog):
    agent._provider.chat = AsyncMock(return_value=_make_response(content="Hello!"))
    with caplog.at_level(logging.INFO, logger="breadmind.agent"):
        await agent.handle_message("hi", user="test", channel="test")

    # Find the llm_call log entry
    llm_call_logs = [
        r for r in caplog.records
        if r.name == "breadmind.agent" and "llm_call" in r.getMessage()
    ]
    assert len(llm_call_logs) >= 1
    log_data = json.loads(llm_call_logs[0].getMessage())
    assert log_data["event"] == "llm_call"
    assert "tokens" in log_data
    assert "duration_ms" in log_data


@pytest.mark.asyncio
async def test_structured_logging_session_events(agent, caplog):
    agent._provider.chat = AsyncMock(return_value=_make_response(content="Hi"))
    with caplog.at_level(logging.INFO, logger="breadmind.agent"):
        await agent.handle_message("hi", user="test", channel="test")

    messages = [r.getMessage() for r in caplog.records if r.name == "breadmind.agent"]
    # Should have session_start and session_end
    assert any("session_start" in m for m in messages)
    assert any("session_end" in m for m in messages)


@pytest.mark.asyncio
async def test_structured_logging_tool_call(agent, caplog):
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="ok"),
    ])
    with caplog.at_level(logging.INFO, logger="breadmind.agent"):
        await agent.handle_message("run", user="test", channel="test")

    tool_call_logs = [
        r for r in caplog.records
        if r.name == "breadmind.agent" and "tool_call" in r.getMessage()
    ]
    assert len(tool_call_logs) >= 1
    log_data = json.loads(tool_call_logs[0].getMessage())
    assert log_data["event"] == "tool_call"
    assert log_data["tool"] == "test_tool"
    assert "duration_ms" in log_data


# --- Audit integration in agent ---

@pytest.mark.asyncio
async def test_agent_audit_logs_llm_call(agent_with_audit):
    agent = agent_with_audit
    agent._provider.chat = AsyncMock(return_value=_make_response(content="Hi"))
    await agent.handle_message("hi", user="test", channel="test")

    entries = agent._audit_logger.get_recent()
    llm_entries = [e for e in entries if e.event_type == "llm_call"]
    assert len(llm_entries) >= 1


@pytest.mark.asyncio
async def test_agent_audit_logs_tool_call(agent_with_audit):
    agent = agent_with_audit
    agent._provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="ok"),
    ])
    await agent.handle_message("run", user="test", channel="test")

    entries = agent._audit_logger.get_recent()
    tool_entries = [e for e in entries if e.event_type == "tool_call"]
    assert len(tool_entries) >= 1
    assert tool_entries[0].details["tool_name"] == "test_tool"


@pytest.mark.asyncio
async def test_agent_audit_logs_safety_check(registry):
    audit = AuditLogger()
    provider = AsyncMock()
    guard = SafetyGuard(blacklist={"test": ["test_tool"]})
    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        audit_logger=audit,
    )

    provider.chat = AsyncMock(side_effect=[
        _make_response(
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "x"})],
        ),
        _make_response(content="blocked"),
    ])
    await agent.handle_message("run", user="test", channel="test")

    entries = audit.get_recent()
    safety_entries = [e for e in entries if e.event_type == "safety_check"]
    assert len(safety_entries) >= 1
    assert safety_entries[0].details["safety_result"] == "DENIED"


# --- Datetime uses timezone-aware UTC ---

def test_datetime_uses_timezone_aware_utc_in_audit():
    audit = AuditLogger()
    entry = audit.log_tool_call(
        user="u", channel="c", tool_name="t",
        arguments={}, result="ok", success=True, duration_ms=10,
    )
    # Timestamp should be timezone-aware (ISO format with +00:00)
    from datetime import datetime as dt
    parsed = dt.fromisoformat(entry.timestamp)
    assert parsed.tzinfo is not None
