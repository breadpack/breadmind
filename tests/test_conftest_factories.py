"""Tests for conftest factory functions and fixtures."""
import pytest

from breadmind.core.protocols import (
    LLMResponse,
    PromptBlock,
    TokenUsage,
    ToolDefinition,
    ToolSchema,
)

from tests.factories import (
    make_agent_context,
    make_mock_prompt_builder,
    make_mock_provider,
    make_mock_tool_registry,
    make_text_response,
    make_tool_call_response,
    make_tool_result,
)


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_mock_provider():
    """make_mock_provider returns a working async provider mock."""
    # Default single text response
    provider = make_mock_provider()
    resp = await provider.chat([], tools=None)
    assert isinstance(resp, LLMResponse)
    assert resp.content == "OK"
    assert resp.tool_calls == []

    # Custom responses
    custom = [
        make_text_response("first"),
        make_text_response("second"),
    ]
    provider2 = make_mock_provider(custom)
    r1 = await provider2.chat([])
    r2 = await provider2.chat([])
    assert r1.content == "first"
    assert r2.content == "second"


def test_make_mock_prompt_builder():
    """make_mock_prompt_builder returns blocks from build()."""
    # Default block
    builder = make_mock_prompt_builder()
    blocks = builder.build()
    assert len(blocks) == 1
    assert blocks[0].section == "identity"
    assert "BreadMind" in blocks[0].content

    # Custom blocks
    custom_blocks = [
        PromptBlock(section="rules", content="Be helpful.", priority=2),
        PromptBlock(section="context", content="Today is Monday.", priority=3),
    ]
    builder2 = make_mock_prompt_builder(custom_blocks)
    result = builder2.build()
    assert len(result) == 2
    assert result[0].section == "rules"


@pytest.mark.asyncio
async def test_make_mock_tool_registry():
    """make_mock_tool_registry returns schemas and executes tools."""
    # Default: empty schemas, OK result
    registry = make_mock_tool_registry()
    assert registry.get_schemas() == []
    result = await registry.execute("call")
    assert result.success is True
    assert result.output == "OK"
    batch = await registry.execute_batch(["c1", "c2"])
    assert len(batch) == 1  # default is single OK

    # Custom schemas and results
    td = ToolDefinition(name="test_tool", description="Test", parameters={})
    schemas = [ToolSchema(name="test_tool", definition=td)]
    results = [make_tool_result("a"), make_tool_result("b")]
    registry2 = make_mock_tool_registry(schemas=schemas, results=results)
    assert len(registry2.get_schemas()) == 1
    assert registry2.get_schemas()[0].name == "test_tool"
    r = await registry2.execute("call")
    assert r.output == "a"
    batch2 = await registry2.execute_batch(["c1", "c2"])
    assert len(batch2) == 2


def test_make_text_response():
    """make_text_response creates a proper LLMResponse."""
    resp = make_text_response("hello world")
    assert resp.content == "hello world"
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 10

    # Custom usage
    resp2 = make_text_response("x", usage=TokenUsage(100, 200))
    assert resp2.usage.input_tokens == 100
    assert resp2.usage.output_tokens == 200


def test_make_tool_call_response():
    """make_tool_call_response creates a response with tool calls."""
    resp = make_tool_call_response([
        ("tc1", "shell_exec", {"cmd": "ls"}),
        ("tc2", "file_read", {"path": "/tmp"}),
    ])
    assert resp.content is None
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "shell_exec"
    assert resp.tool_calls[1].id == "tc2"
    assert resp.stop_reason == "tool_use"


def test_make_agent_context():
    """make_agent_context creates an AgentContext with defaults."""
    ctx = make_agent_context()
    assert ctx.user == "test_user"
    assert ctx.channel == "test"
    assert ctx.session_id  # not empty

    ctx2 = make_agent_context(user="admin", channel="cli", session_id="s42")
    assert ctx2.user == "admin"
    assert ctx2.channel == "cli"
    assert ctx2.session_id == "s42"


# ---------------------------------------------------------------------------
# Fixture tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_loop_agent_fixture(message_loop_agent, agent_context):
    """The message_loop_agent fixture produces a working agent."""
    resp = await message_loop_agent.handle_message("hello", agent_context)
    assert resp.content == "OK"
    assert resp.tool_calls_count == 0


@pytest.mark.asyncio
async def test_factories_compose():
    """Factories can be composed for custom multi-turn scenarios."""
    # Scenario: tool call -> tool result -> final answer
    provider = make_mock_provider([
        make_tool_call_response([("tc1", "ping", {"host": "8.8.8.8"})]),
        make_text_response("Ping succeeded."),
    ])

    td = ToolDefinition(name="ping", description="Ping host", parameters={})
    registry = make_mock_tool_registry(
        schemas=[ToolSchema(name="ping", definition=td)],
        results=[make_tool_result("64 bytes from 8.8.8.8")],
    )

    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    from breadmind.plugins.builtin.safety.guard import SafetyGuard

    agent = MessageLoopAgent(
        provider=provider,
        prompt_builder=make_mock_prompt_builder(),
        tool_registry=registry,
        safety_guard=SafetyGuard(autonomy="auto"),
        max_turns=5,
    )

    ctx = make_agent_context(user="ops", channel="slack")
    resp = await agent.handle_message("ping 8.8.8.8", ctx)

    assert "succeeded" in resp.content.lower()
    assert resp.tool_calls_count == 1
    assert provider.chat.call_count == 2
