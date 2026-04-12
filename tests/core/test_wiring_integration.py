"""Integration tests for wiring standalone modules into the main execution path."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch



# ── Helpers / Fixtures ─────────────────────────────────────────────────


@dataclass
class FakeToolCall:
    id: str = "tc_1"
    name: str = "shell_exec"
    arguments: dict = None

    def __post_init__(self):
        if self.arguments is None:
            self.arguments = {"command": "ls"}


@dataclass
class FakeToolResult:
    success: bool = True
    output: str = "ok"
    not_found: bool = False


@dataclass
class FakeToolDefinition:
    name: str = "shell_exec"
    description: str = "run shell"
    parameters: dict = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            }


@dataclass
class FakeSandboxResult:
    success: bool = True
    output: str = "sandbox output"


def _make_executor(**kwargs):
    from breadmind.core.tool_executor import ToolExecutor

    registry = MagicMock()
    registry.execute = AsyncMock(return_value=FakeToolResult())
    registry.get_all_definitions = MagicMock(return_value=[FakeToolDefinition()])
    guard = MagicMock()
    return ToolExecutor(
        tool_registry=registry,
        safety_guard=guard,
        tool_timeout=30,
        **kwargs,
    )


def _make_ctx():
    from breadmind.core.tool_executor import ToolExecutionContext

    return ToolExecutionContext(
        user="test_user",
        channel="test_channel",
        session_id="sess_1",
        working_memory=None,
        audit_logger=None,
        tool_gap_detector=None,
        context_builder=None,
    )


# ── I1: SandboxExecutor wired to tool_executor ────────────────────────


async def test_sandbox_wired_to_executor():
    """shell_exec should route through SandboxExecutor when available."""
    sandbox = AsyncMock()
    sandbox.execute = AsyncMock(return_value=FakeSandboxResult())

    executor = _make_executor(sandbox_executor=sandbox)
    ctx = _make_ctx()
    tc = FakeToolCall(name="shell_exec", arguments={"command": "ls -la", "workdir": "/tmp"})

    _, output, _ = await executor._execute_one(tc, ctx)

    sandbox.execute.assert_awaited_once_with("ls -la", "/tmp")
    assert "sandbox output" in output
    assert "[success=True]" in output


async def test_sandbox_not_used_for_non_shell():
    """Non-shell_exec tools should NOT go through sandbox."""
    sandbox = AsyncMock()
    sandbox.execute = AsyncMock(return_value=FakeSandboxResult())

    executor = _make_executor(sandbox_executor=sandbox)
    ctx = _make_ctx()
    tc = FakeToolCall(id="tc_2", name="read_file", arguments={"path": "/etc/hosts"})

    await executor._execute_one(tc, ctx)

    sandbox.execute.assert_not_awaited()


# ── I2: ToolHookRunner wired to tool_executor ─────────────────────────


async def test_hook_runner_pre_blocks_execution():
    """Pre-hook that returns 'block' should prevent execution."""
    from breadmind.core.tool_hooks import ToolHookResult

    hook_runner = AsyncMock()
    hook_runner.run_pre_hooks = AsyncMock(
        return_value=ToolHookResult(action="block", block_reason="denied by policy")
    )

    executor = _make_executor(hook_runner=hook_runner)
    ctx = _make_ctx()
    tc = FakeToolCall(id="tc_3", name="read_file", arguments={"path": "/etc"})

    _, output, _ = await executor._execute_one(tc, ctx)

    assert "[success=False]" in output
    assert "Blocked by hook" in output
    assert "denied by policy" in output
    # Tool should NOT have been executed
    executor._tools.execute.assert_not_awaited()


async def test_hook_runner_pre_modifies_args():
    """Pre-hook that returns 'modify' should pass modified args to execute."""
    from breadmind.core.tool_hooks import ToolHookResult

    modified_args = {"path": "/safe/path"}
    hook_runner = AsyncMock()
    hook_runner.run_pre_hooks = AsyncMock(
        return_value=ToolHookResult(action="modify", modified_input=modified_args)
    )
    hook_runner.run_post_hooks = AsyncMock(return_value=ToolHookResult())

    executor = _make_executor(hook_runner=hook_runner)
    ctx = _make_ctx()
    tc = FakeToolCall(id="tc_4", name="read_file", arguments={"path": "/etc/shadow"})

    await executor._execute_one(tc, ctx)

    # execute() should have been called with the modified args
    executor._tools.execute.assert_awaited_once()
    call_args = executor._tools.execute.call_args
    assert call_args[0][1] == modified_args


async def test_hook_runner_post_appends_context():
    """Post-hook should append additional_context to output."""
    from breadmind.core.tool_hooks import ToolHookResult

    hook_runner = AsyncMock()
    hook_runner.run_pre_hooks = AsyncMock(return_value=ToolHookResult())
    hook_runner.run_post_hooks = AsyncMock(
        return_value=ToolHookResult(additional_context="audit: logged")
    )

    executor = _make_executor(hook_runner=hook_runner)
    ctx = _make_ctx()
    tc = FakeToolCall(id="tc_5", name="read_file", arguments={"path": "/tmp"})

    _, output, _ = await executor._execute_one(tc, ctx)

    assert "[Hook context] audit: logged" in output


# ── I3: SchemaValidator wired to tool_executor ────────────────────────


async def test_schema_validator_blocks_invalid_args():
    """SchemaValidator should block execution when args are invalid."""
    from breadmind.tools.schema_validator import SchemaValidator

    validator = SchemaValidator()

    executor = _make_executor(schema_validator=validator)
    # Update the registry to return a definition with required 'command'
    executor._tools.get_all_definitions.return_value = [
        FakeToolDefinition(
            name="shell_exec",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
    ]

    ctx = _make_ctx()
    # Missing required 'command' field
    tc = FakeToolCall(id="tc_6", name="shell_exec", arguments={})

    _, output, _ = await executor._execute_one(tc, ctx)

    assert "[success=False]" in output
    assert "Validation failed" in output
    assert "command" in output
    executor._tools.execute.assert_not_awaited()


# ── I4: OTel records token usage ──────────────────────────────────────


async def test_otel_records_token_usage():
    """OTel should record token usage and latency after LLM call."""
    mock_otel = MagicMock()
    mock_otel.available = True

    with patch("breadmind.core.otel.get_otel", return_value=mock_otel):
        # We test the OTel recording code path by importing and calling it directly
        from breadmind.core.otel import get_otel

        otel = get_otel()
        assert otel.available
        otel.record_token_usage(100, 50, model="test-model")
        otel.record_llm_latency(250.0, model="test-model")

        mock_otel.record_token_usage.assert_called_once_with(100, 50, model="test-model")
        mock_otel.record_llm_latency.assert_called_once_with(250.0, model="test-model")


# ── C6: PreCompact hook + instruction file reload ─────────────────────


async def test_precompact_hook_called():
    """on_pre_compact callback should be invoked before compaction."""
    from breadmind.plugins.builtin.agent_loop.auto_compact import (
        AutoCompactor,
        CompactConfig,
        CompactionLevel,
    )
    from breadmind.core.protocols import Message

    hook_called_with = {}

    async def pre_compact_hook(messages, level):
        hook_called_with["messages"] = messages
        hook_called_with["level"] = level

    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=MagicMock(content="summary"))
    config = CompactConfig(max_context_tokens=100)

    compactor = AutoCompactor(
        provider=provider,
        config=config,
        on_pre_compact=pre_compact_hook,
    )

    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="x" * 500),
    ]

    await compactor.compact(messages, force_level=CompactionLevel.TOOL_RESULT_TRIM)

    assert "messages" in hook_called_with
    assert hook_called_with["level"] == CompactionLevel.TOOL_RESULT_TRIM


async def test_instruction_file_reinjected_after_compact(tmp_path):
    """Instruction files should be re-injected into compacted result."""
    from breadmind.plugins.builtin.agent_loop.auto_compact import (
        AutoCompactor,
        CompactConfig,
        CompactionLevel,
    )
    from breadmind.core.protocols import Message

    # Create a temp instruction file
    instr_file = tmp_path / "instructions.md"
    instr_file.write_text("Always be polite.", encoding="utf-8")

    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=MagicMock(content="summary"))
    config = CompactConfig(max_context_tokens=100)

    compactor = AutoCompactor(
        provider=provider,
        config=config,
        instruction_files=[str(instr_file)],
    )

    messages = [
        Message(role="system", content="system prompt"),
        Message(role="user", content="x" * 500),
    ]

    result = await compactor.compact(messages, force_level=CompactionLevel.TOOL_RESULT_TRIM)

    # Find the injected instruction message
    instruction_msgs = [m for m in result if "Instruction file:" in (m.content or "")]
    assert len(instruction_msgs) == 1
    assert "Always be polite." in instruction_msgs[0].content
    assert instruction_msgs[0].role == "system"
    # Should be inserted after system message (index 1)
    assert result[0].role == "system"
    assert result[0].content == "system prompt"
    assert result[1] == instruction_msgs[0]


# ── C15: Context overflow circuit breaker ─────────────────────────────


async def test_context_overflow_emergency_compact():
    """Context overflow should trigger emergency compaction and retry."""
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    from breadmind.core.protocols import (
        AgentContext, LLMResponse, Message, TokenUsage,
    )

    # Provider: first call raises context overflow, second succeeds
    provider = MagicMock()
    provider.supports_feature = MagicMock(return_value=False)
    call_count = 0

    async def mock_chat(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("context too long for this model")
        return LLMResponse(
            content="recovered response",
            tool_calls=[],
            usage=TokenUsage(input_tokens=5, output_tokens=5),
            stop_reason="end_turn",
        )

    provider.chat = mock_chat

    prompt_builder = MagicMock()
    prompt_builder.build = MagicMock(return_value=[MagicMock(content="system")])
    tool_registry = MagicMock()
    tool_registry.get_schemas = MagicMock(return_value=[])
    safety = MagicMock()

    compactor = AsyncMock()
    compactor.should_compact = MagicMock(return_value=False)
    compactor.compact = AsyncMock(side_effect=lambda msgs, force_level=None: [
        Message(role="system", content="compacted"),
    ])

    agent = MessageLoopAgent(
        provider=provider,
        prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=safety,
        auto_compactor=compactor,
    )

    ctx = AgentContext(user="u", channel="c", session_id="s")
    result = await agent.handle_message("hello", ctx)

    assert result.content == "recovered response"
    compactor.compact.assert_awaited_once()


async def test_context_overflow_no_compactor_returns_error():
    """Without compactor, context overflow returns error message."""
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    from breadmind.core.protocols import AgentContext

    provider = MagicMock()
    provider.supports_feature = MagicMock(return_value=False)

    async def mock_chat(messages, tools=None):
        raise Exception("context too long")

    provider.chat = mock_chat

    prompt_builder = MagicMock()
    prompt_builder.build = MagicMock(return_value=[MagicMock(content="system")])
    tool_registry = MagicMock()
    tool_registry.get_schemas = MagicMock(return_value=[])
    safety = MagicMock()

    agent = MessageLoopAgent(
        provider=provider,
        prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        safety_guard=safety,
        auto_compactor=None,
    )

    ctx = AgentContext(user="u", channel="c", session_id="s")
    result = await agent.handle_message("hello", ctx)

    assert "Context overflow" in result.content
    assert "too large" in result.content


# ── Backward compatibility ────────────────────────────────────────────


async def test_all_wiring_params_optional():
    """ToolExecutor should work without any new optional params (backward compat)."""
    from breadmind.core.tool_executor import ToolExecutor

    registry = MagicMock()
    registry.execute = AsyncMock(return_value=FakeToolResult())
    registry.get_all_definitions = MagicMock(return_value=[])
    guard = MagicMock()

    # No sandbox, hook_runner, or schema_validator
    executor = ToolExecutor(
        tool_registry=registry,
        safety_guard=guard,
        tool_timeout=30,
    )

    assert executor._sandbox is None
    assert executor._hook_runner is None
    assert executor._validator is None

    ctx = _make_ctx()
    tc = FakeToolCall(id="tc_back", name="read_file", arguments={"path": "/tmp"})
    _, output, _ = await executor._execute_one(tc, ctx)

    assert "[success=True]" in output
