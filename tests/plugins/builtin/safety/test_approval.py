"""Tests for the approval flow."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.core.events import EventBus
from breadmind.core.protocols import (
    AgentContext, LLMResponse, Message, PromptBlock, ToolCallRequest,
    TokenUsage, ToolResult,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.approval import (
    ApprovalRequest,
    ApprovalResponse,
    AutoApproveHandler,
    AutoDenyHandler,
    CallbackApprovalHandler,
    EventBusApprovalHandler,
)
from breadmind.plugins.builtin.safety.guard import SafetyVerdict


# ── Unit tests: handlers ──────────────────────────────────────────────


@pytest.fixture
def sample_request() -> ApprovalRequest:
    return ApprovalRequest.create(
        tool_name="shell_exec",
        arguments={"command": "rm -rf /tmp/test"},
        reason="Destructive action detected",
    )


async def test_auto_approve_handler(sample_request: ApprovalRequest):
    handler = AutoApproveHandler()
    resp = await handler.request_approval(sample_request)
    assert resp.approved is True
    assert resp.request_id == sample_request.request_id


async def test_auto_deny_handler(sample_request: ApprovalRequest):
    handler = AutoDenyHandler()
    resp = await handler.request_approval(sample_request)
    assert resp.approved is False
    assert resp.request_id == sample_request.request_id


async def test_callback_handler(sample_request: ApprovalRequest):
    async def my_callback(req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(request_id=req.request_id, approved=True)

    handler = CallbackApprovalHandler(my_callback)
    resp = await handler.request_approval(sample_request)
    assert resp.approved is True


async def test_callback_handler_receives_request(sample_request: ApprovalRequest):
    received = []

    async def capture(req: ApprovalRequest) -> ApprovalResponse:
        received.append(req)
        return ApprovalResponse(request_id=req.request_id, approved=False)

    handler = CallbackApprovalHandler(capture)
    resp = await handler.request_approval(sample_request)
    assert resp.approved is False
    assert len(received) == 1
    assert received[0].tool_name == "shell_exec"


# ── EventBusApprovalHandler ──────────────────────────────────────────


async def test_event_bus_handler_emits_event(sample_request: ApprovalRequest):
    bus = EventBus()
    handler = EventBusApprovalHandler(bus, timeout=5.0)

    emitted = []
    bus.on("approval_requested", lambda data: emitted.append(data))

    # resolve in background after a tiny delay
    async def resolve_soon():
        await asyncio.sleep(0.01)
        handler.resolve(sample_request.request_id, approved=True)

    task = asyncio.create_task(resolve_soon())
    resp = await handler.request_approval(sample_request)
    await task

    assert resp.approved is True
    assert len(emitted) == 1
    assert emitted[0]["tool_name"] == "shell_exec"


async def test_event_bus_handler_resolve_approved(sample_request: ApprovalRequest):
    bus = EventBus()
    handler = EventBusApprovalHandler(bus, timeout=5.0)

    async def resolve_soon():
        await asyncio.sleep(0.01)
        handler.resolve(sample_request.request_id, approved=True)

    task = asyncio.create_task(resolve_soon())
    resp = await handler.request_approval(sample_request)
    await task

    assert resp.approved is True
    assert handler.pending_count == 0


async def test_event_bus_handler_resolve_denied(sample_request: ApprovalRequest):
    bus = EventBus()
    handler = EventBusApprovalHandler(bus, timeout=5.0)

    async def resolve_soon():
        await asyncio.sleep(0.01)
        handler.resolve(sample_request.request_id, approved=False)

    task = asyncio.create_task(resolve_soon())
    resp = await handler.request_approval(sample_request)
    await task

    assert resp.approved is False


async def test_event_bus_handler_timeout():
    bus = EventBus()
    handler = EventBusApprovalHandler(bus, timeout=0.05)

    request = ApprovalRequest.create(
        tool_name="shell_exec",
        arguments={"command": "dangerous"},
        reason="test",
    )
    resp = await handler.request_approval(request)
    assert resp.approved is False  # timeout → auto-deny


async def test_event_bus_handler_modified_arguments(sample_request: ApprovalRequest):
    bus = EventBus()
    handler = EventBusApprovalHandler(bus, timeout=5.0)
    modified = {"command": "ls -la /tmp/test"}

    async def resolve_soon():
        await asyncio.sleep(0.01)
        handler.resolve(
            sample_request.request_id, approved=True,
            modified_arguments=modified,
        )

    task = asyncio.create_task(resolve_soon())
    resp = await handler.request_approval(sample_request)
    await task

    assert resp.approved is True
    assert resp.modified_arguments == modified


# ── ApprovalRequest/Response serialization ────────────────────────────


def test_approval_request_to_dict(sample_request: ApprovalRequest):
    d = sample_request.to_dict()
    assert d["tool_name"] == "shell_exec"
    assert isinstance(d["timestamp"], str)  # ISO format string
    assert d["request_id"] == sample_request.request_id


def test_approval_response_to_dict():
    resp = ApprovalResponse(request_id="abc123", approved=True, modified_arguments={"x": 1})
    d = resp.to_dict()
    assert d["request_id"] == "abc123"
    assert d["approved"] is True
    assert d["modified_arguments"] == {"x": 1}


# ── MessageLoopAgent integration ─────────────────────────────────────


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
    registry.execute_batch = AsyncMock(return_value=[ToolResult(success=True, output="executed")])
    return registry


def _make_agent(provider, prompt_builder, tool_registry, safety, approval_handler=None):
    return MessageLoopAgent(
        provider=provider,
        prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=safety,
        max_turns=5,
        approval_handler=approval_handler,
    )


async def test_needs_approval_approved_then_executed(
    mock_provider, mock_prompt_builder, mock_tool_registry,
):
    """needs_approval + 승인 → 도구 실행."""
    safety = MagicMock()
    safety.check.return_value = SafetyVerdict(
        allowed=True, needs_approval=True, reason="Destructive",
    )

    handler = AutoApproveHandler()
    agent = _make_agent(
        mock_provider, mock_prompt_builder, mock_tool_registry,
        safety, approval_handler=handler,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "rm"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete files", ctx)

    assert resp.content == "Done."
    assert resp.tool_calls_count == 1
    mock_tool_registry.execute_batch.assert_called_once()


async def test_needs_approval_denied_then_blocked(
    mock_provider, mock_prompt_builder, mock_tool_registry,
):
    """needs_approval + 거부 → 도구 실행하지 않음."""
    safety = MagicMock()
    safety.check.return_value = SafetyVerdict(
        allowed=True, needs_approval=True, reason="Destructive",
    )

    handler = AutoDenyHandler()
    agent = _make_agent(
        mock_provider, mock_prompt_builder, mock_tool_registry,
        safety, approval_handler=handler,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "rm"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="OK, cancelled.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete files", ctx)

    assert resp.content == "OK, cancelled."
    # execute_batch should NOT have been called (no allowed_calls)
    mock_tool_registry.execute_batch.assert_not_called()


async def test_no_approval_handler_ignores_needs_approval(
    mock_provider, mock_prompt_builder, mock_tool_registry,
):
    """approval_handler=None → needs_approval 무시하고 실행 (기존 동작 유지)."""
    safety = MagicMock()
    safety.check.return_value = SafetyVerdict(
        allowed=True, needs_approval=True, reason="Destructive",
    )

    agent = _make_agent(
        mock_provider, mock_prompt_builder, mock_tool_registry,
        safety, approval_handler=None,  # no handler
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "rm"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete files", ctx)

    assert resp.content == "Done."
    mock_tool_registry.execute_batch.assert_called_once()


async def test_modified_arguments_applied(
    mock_provider, mock_prompt_builder, mock_tool_registry,
):
    """승인 시 modified_arguments가 도구 실행에 반영됨."""
    safety = MagicMock()
    safety.check.return_value = SafetyVerdict(
        allowed=True, needs_approval=True, reason="Destructive",
    )

    modified_args = {"cmd": "ls -la"}

    async def approve_with_modification(req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(
            request_id=req.request_id,
            approved=True,
            modified_arguments=modified_args,
        )

    handler = CallbackApprovalHandler(approve_with_modification)
    agent = _make_agent(
        mock_provider, mock_prompt_builder, mock_tool_registry,
        safety, approval_handler=handler,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "rm -rf /"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Listed.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("delete files", ctx)

    assert resp.content == "Listed."
    # Verify the tool was called with modified arguments
    call_args = mock_tool_registry.execute_batch.call_args
    executed_calls = call_args[0][0]
    assert executed_calls[0].arguments == modified_args
