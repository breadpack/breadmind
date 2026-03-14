import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard, SafetyResult
from breadmind.tools.registry import ToolRegistry, tool, ToolResult
from breadmind.memory.working import WorkingMemory
from breadmind.monitoring.engine import MonitoringEngine, MonitoringEvent, MonitoringRule
from breadmind.web.app import WebApp
from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall, TokenUsage, ToolDefinition


# --- Helpers ---

def _make_usage():
    return TokenUsage(input_tokens=10, output_tokens=20)


def _text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], usage=_make_usage(), stop_reason="end_turn")


def _tool_call_response(tool_name: str, arguments: dict, call_id: str = "call_1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=arguments)],
        usage=_make_usage(),
        stop_reason="tool_use",
    )


# --- Test 1: Agent + WorkingMemory multi-turn ---

@pytest.mark.asyncio
async def test_agent_working_memory_multi_turn():
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=[
        _text_response("Hello! How can I help?"),
        _text_response("Sure, I remember the previous context."),
    ])

    registry = ToolRegistry()
    guard = SafetyGuard()
    memory = WorkingMemory()

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        working_memory=memory,
    )

    # First message
    resp1 = await agent.handle_message("Hi there", user="user1", channel="general")
    assert resp1 == "Hello! How can I help?"

    # Verify message stored in memory
    messages = memory.get_messages("user1:general")
    assert len(messages) == 2  # user msg + assistant msg

    # Second message
    resp2 = await agent.handle_message("Do you remember?", user="user1", channel="general")
    assert resp2 == "Sure, I remember the previous context."

    # Verify the second provider call includes previous context
    second_call_messages = provider.chat.call_args_list[1][1]["messages"]
    # Should have: system + prev_user + prev_assistant + new_user
    assert len(second_call_messages) >= 4
    assert second_call_messages[0].role == "system"


# --- Test 2: Agent + SafetyGuard + ToolRegistry (blocked tool) ---

@pytest.mark.asyncio
async def test_agent_safety_guard_blocks_blacklisted_tool():
    provider = AsyncMock(spec=LLMProvider)
    # First call returns tool call, second call returns text after seeing blocked result
    provider.chat = AsyncMock(side_effect=[
        _tool_call_response("dangerous_tool", {"target": "prod"}),
        _text_response("The tool was blocked for safety reasons."),
    ])

    registry = ToolRegistry()
    guard = SafetyGuard(blacklist={"dangerous": ["dangerous_tool"]})

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    resp = await agent.handle_message("Run dangerous_tool on prod", user="admin", channel="ops")
    assert "blocked" in resp.lower() or "safety" in resp.lower() or resp == "The tool was blocked for safety reasons."

    # Verify the provider received the BLOCKED message
    second_call_messages = provider.chat.call_args_list[1][1]["messages"]
    tool_msg = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_msg) == 1
    assert "BLOCKED" in tool_msg[0].content


# --- Test 3: Agent + ToolRegistry tool execution ---

@pytest.mark.asyncio
async def test_agent_tool_execution_flow():
    @tool("Add two numbers")
    def add_numbers(a: int, b: int) -> str:
        return str(int(a) + int(b))

    registry = ToolRegistry()
    registry.register(add_numbers)
    guard = SafetyGuard()

    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=[
        _tool_call_response("add_numbers", {"a": "3", "b": "4"}),
        _text_response("The result is 7."),
    ])

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    resp = await agent.handle_message("What is 3+4?", user="user1", channel="math")
    assert "7" in resp

    # Verify tool result was passed back to provider
    second_call_messages = provider.chat.call_args_list[1][1]["messages"]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "7" in tool_msgs[0].content
    assert "[success=True]" in tool_msgs[0].content


# --- Test 4: WebApp + Agent integration ---

@pytest.mark.asyncio
async def test_webapp_agent_health_and_tools():
    @tool("Test tool")
    def test_tool(x: str) -> str:
        return x

    registry = ToolRegistry()
    registry.register(test_tool)

    provider = AsyncMock(spec=LLMProvider)
    guard = SafetyGuard()

    agent = CoreAgent(provider=provider, tool_registry=registry, safety_guard=guard)

    webapp = WebApp(
        message_handler=agent.handle_message,
        tool_registry=registry,
    )
    client = TestClient(webapp.app)

    # Health check should be OK since message_handler is set
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["components"]["agent"] is True

    # Tools endpoint should list our tool
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "test_tool"


# --- Test 5: MonitoringEngine + WebApp events ---

@pytest.mark.asyncio
async def test_monitoring_engine_webapp_events():
    webapp = WebApp(message_handler=lambda m, **kw: "ok")

    engine = MonitoringEngine(on_event=webapp.on_monitoring_event)

    def emit_event(state, prev):
        return [MonitoringEvent(
            source="test", target="test:1", severity="info", condition="test_event"
        )]

    engine.add_rule_sync(MonitoringRule(name="test_rule", source="test", condition_fn=emit_event))

    # Run check_once which will trigger the event callback
    events = await engine.check_once()
    assert len(events) == 1

    # Manually trigger the on_event callback (check_once doesn't call on_event)
    await webapp.on_monitoring_event(events[0])

    # Verify event appears in webapp
    assert len(webapp._events) == 1
    assert webapp._events[0]["condition"] == "test_event"


# --- Test 6: Full pipeline mock ---

@pytest.mark.asyncio
async def test_full_pipeline():
    """Agent receives message -> calls tool -> safety allows -> tool executes -> response returned."""

    @tool("Get server status")
    def get_status(server: str) -> str:
        return f"{server} is healthy"

    registry = ToolRegistry()
    registry.register(get_status)
    guard = SafetyGuard()
    memory = WorkingMemory()

    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=[
        _tool_call_response("get_status", {"server": "web-01"}),
        _text_response("Server web-01 is healthy."),
    ])

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        working_memory=memory,
    )

    webapp = WebApp(
        message_handler=agent.handle_message,
        tool_registry=registry,
    )

    # Simulate the full flow through agent
    resp = await agent.handle_message("Check web-01 status", user="ops", channel="infra")
    assert "healthy" in resp.lower()

    # Verify memory has the full conversation
    messages = memory.get_messages("ops:infra")
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    assert "tool" in roles

    # Verify webapp health is ok
    client = TestClient(webapp.app)
    health_resp = client.get("/health")
    assert health_resp.status_code == 200


# --- Test 7: Concurrent message handling ---

@pytest.mark.asyncio
async def test_concurrent_message_handling():
    call_count = 0

    async def mock_chat(messages, tools=None, model=None):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)  # Simulate small delay
        return _text_response(f"Response {call_count}")

    provider = AsyncMock(spec=LLMProvider)
    provider.chat = mock_chat

    registry = ToolRegistry()
    guard = SafetyGuard()
    memory = WorkingMemory()

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        working_memory=memory,
    )

    # Send 5 messages concurrently from different users
    tasks = [
        agent.handle_message(f"Message {i}", user=f"user{i}", channel="test")
        for i in range(5)
    ]
    responses = await asyncio.gather(*tasks)

    # All 5 should get responses (no crashes, no race conditions)
    assert len(responses) == 5
    for resp in responses:
        assert resp is not None
        assert isinstance(resp, str)
        assert len(resp) > 0


# --- Test 8: Error resilience ---

@pytest.mark.asyncio
async def test_error_resilience_provider_failure():
    """Provider fails - agent returns error message gracefully."""
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=RuntimeError("LLM service unavailable"))

    registry = ToolRegistry()
    guard = SafetyGuard()

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    resp = await agent.handle_message("Hello", user="user1", channel="test")
    # Agent should return an error message, not crash
    assert isinstance(resp, str)
    assert len(resp) > 0


@pytest.mark.asyncio
async def test_error_resilience_tool_exception():
    """Tool throws exception - agent handles gracefully and continues."""

    @tool("Failing tool")
    def failing_tool() -> str:
        raise ValueError("Something went wrong")

    registry = ToolRegistry()
    registry.register(failing_tool)
    guard = SafetyGuard()

    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=[
        _tool_call_response("failing_tool", {}),
        _text_response("The tool encountered an error, but I can help another way."),
    ])

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

    resp = await agent.handle_message("Run the failing tool", user="user1", channel="test")
    assert isinstance(resp, str)

    # Verify the error was passed back to the provider
    second_call_messages = provider.chat.call_args_list[1][1]["messages"]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "[success=False]" in tool_msgs[0].content
    assert "Something went wrong" in tool_msgs[0].content


# --- Test: MonitoringEngine graceful stop ---

@pytest.mark.asyncio
async def test_monitoring_engine_graceful_stop():
    events_received = []

    async def on_event(event):
        events_received.append(event)

    def slow_rule(state, prev):
        return [MonitoringEvent(source="test", target="t:1", severity="info", condition="tick")]

    engine = MonitoringEngine(on_event=on_event)
    engine.add_rule_sync(MonitoringRule(
        name="slow", source="test", condition_fn=slow_rule, interval_seconds=1
    ))

    await engine.start()
    assert engine._running is True

    # Let it run briefly
    await asyncio.sleep(0.1)

    # Graceful stop
    await engine.stop()
    assert engine._running is False
    assert len(engine._tasks) == 0


# --- Test: WebApp health returns 503 when no handler ---

def test_webapp_health_503_no_handler():
    webapp = WebApp()
    client = TestClient(webapp.app)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["components"]["agent"] is False
    assert data["components"]["monitoring"] is False
