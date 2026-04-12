"""Tests for the Pre/Post tool-use hook system."""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.plugins.builtin.safety.hooks import HookDefinition, HookResult, HookRunner
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.core.protocols import (
    AgentContext, LLMResponse, PromptBlock, TokenUsage,
    ToolCallRequest, ToolResult,
)
from breadmind.plugins.builtin.safety.guard import SafetyVerdict


# ── HookRunner unit tests ────────────────────────────────────────────


@pytest.fixture
def runner():
    return HookRunner()


def test_register_and_unregister(runner):
    hook = HookDefinition(event="pre_tool_use", tool_pattern="shell_*", command="echo ok")
    runner.register(hook)
    assert len(runner._hooks) == 1

    runner.unregister("pre_tool_use", "shell_*")
    assert len(runner._hooks) == 0


def test_unregister_nonexistent_is_noop(runner):
    runner.unregister("pre_tool_use", "no_match")
    assert len(runner._hooks) == 0


def test_glob_pattern_matching(runner):
    hook = HookDefinition(event="pre_tool_use", tool_pattern="shell_*", command="echo ok")
    runner.register(hook)
    matches = runner._matching_hooks("pre_tool_use", "shell_exec")
    assert len(matches) == 1

    no_matches = runner._matching_hooks("pre_tool_use", "file_read")
    assert len(no_matches) == 0


def test_wildcard_pattern_matches_all(runner):
    hook = HookDefinition(event="pre_tool_use", tool_pattern="*", command="echo ok")
    runner.register(hook)
    assert len(runner._matching_hooks("pre_tool_use", "shell_exec")) == 1
    assert len(runner._matching_hooks("pre_tool_use", "k8s_pods_list")) == 1


def test_event_type_filtering(runner):
    runner.register(HookDefinition(event="pre_tool_use", tool_pattern="*", command="echo pre"))
    runner.register(HookDefinition(event="post_tool_use", tool_pattern="*", command="echo post"))
    assert len(runner._matching_hooks("pre_tool_use", "shell_exec")) == 1
    assert len(runner._matching_hooks("post_tool_use", "shell_exec")) == 1


# ── Async execution tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_tool_use_passes_on_success(runner):
    # Use python -c for cross-platform compatibility
    hook = HookDefinition(
        event="pre_tool_use", tool_pattern="shell_*",
        command="import os; print(os.environ.get('TOOL_NAME', ''))",
    )
    runner.register(hook)
    result = await runner.run_pre_tool_use("shell_exec", {"command": "ls"})
    assert result.passed is True
    assert "shell_exec" in result.output


@pytest.mark.asyncio
async def test_pre_tool_use_fails_on_nonzero_exit(runner):
    hook = HookDefinition(
        event="pre_tool_use", tool_pattern="*",
        command="import sys; sys.exit(1)",
    )
    runner.register(hook)
    result = await runner.run_pre_tool_use("shell_exec", {"command": "rm -rf /"})
    assert result.passed is False


@pytest.mark.asyncio
async def test_pre_tool_use_no_hooks_passes(runner):
    result = await runner.run_pre_tool_use("shell_exec", {})
    assert result.passed is True


@pytest.mark.asyncio
async def test_post_tool_use_always_passes(runner):
    """Post-tool hooks always return passed=True even if command fails."""
    hook = HookDefinition(
        event="post_tool_use", tool_pattern="*",
        command="import sys; sys.exit(1)",
    )
    runner.register(hook)
    result = await runner.run_post_tool_use("shell_exec", {}, "output")
    assert result.passed is True


@pytest.mark.asyncio
async def test_post_tool_use_receives_result_env(runner):
    hook = HookDefinition(
        event="post_tool_use", tool_pattern="*",
        command="import os; print(os.environ.get('TOOL_RESULT', ''))",
    )
    runner.register(hook)
    result = await runner.run_post_tool_use("shell_exec", {}, "my_result_data")
    assert result.passed is True
    assert "my_result_data" in result.output


@pytest.mark.asyncio
async def test_timeout_handling(runner):
    hook = HookDefinition(
        event="pre_tool_use", tool_pattern="*",
        command="import time; time.sleep(30)",
        timeout=1,
    )
    runner.register(hook)
    result = await runner.run_pre_tool_use("shell_exec", {})
    assert result.passed is False
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_env_variables_passed_correctly(runner):
    hook = HookDefinition(
        event="pre_tool_use", tool_pattern="*",
        command="import os, json; args = json.loads(os.environ['TOOL_ARGS']); print(args['key'])",
    )
    runner.register(hook)
    result = await runner.run_pre_tool_use("test_tool", {"key": "value123"})
    assert result.passed is True
    assert "value123" in result.output


@pytest.mark.asyncio
async def test_multiple_pre_hooks_first_failure_stops(runner):
    runner.register(HookDefinition(
        event="pre_tool_use", tool_pattern="*",
        command="import sys; sys.exit(1)",
    ))
    runner.register(HookDefinition(
        event="pre_tool_use", tool_pattern="*",
        command="print('should not run')",
    ))
    result = await runner.run_pre_tool_use("shell_exec", {})
    assert result.passed is False


# ── MessageLoopAgent integration ──────────────────────────────────────


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.supports_feature = MagicMock(return_value=False)
    provider.fallback = None
    return provider


@pytest.fixture
def mock_prompt_builder():
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="test", content="Test prompt.", cacheable=True, priority=0),
    ]
    return builder


@pytest.fixture
def mock_tool_registry():
    registry = MagicMock()
    registry.get_schemas.return_value = []
    registry.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    # Remove auto-generated execute_batch so hasattr check falls through to execute
    del registry.execute_batch
    return registry


@pytest.fixture
def mock_safety():
    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)
    return guard


@pytest.mark.asyncio
async def test_agent_blocks_tool_on_pre_hook_failure(
    mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
):
    hook_runner = AsyncMock(spec=HookRunner)
    hook_runner.run_pre_tool_use.return_value = HookResult(
        passed=False, error="Hook denied",
    )

    agent = MessageLoopAgent(
        provider=mock_provider, prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry, safety_guard=mock_safety,
        max_turns=2, hook_runner=hook_runner,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "ls"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Blocked.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("do something", ctx)

    # Tool should NOT have been executed
    mock_tool_registry.execute.assert_not_called()
    hook_runner.run_pre_tool_use.assert_called_once()


@pytest.mark.asyncio
async def test_agent_calls_post_hook_after_execution(
    mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
):
    hook_runner = AsyncMock(spec=HookRunner)
    hook_runner.run_pre_tool_use.return_value = HookResult(passed=True)
    hook_runner.run_post_tool_use.return_value = HookResult(passed=True)

    agent = MessageLoopAgent(
        provider=mock_provider, prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry, safety_guard=mock_safety,
        max_turns=2, hook_runner=hook_runner,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "ls"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    await agent.handle_message("do something", ctx)

    mock_tool_registry.execute.assert_called_once()
    hook_runner.run_post_tool_use.assert_called_once()


@pytest.mark.asyncio
async def test_agent_works_without_hook_runner(
    mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
):
    """hook_runner=None이면 기존 동작 유지."""
    agent = MessageLoopAgent(
        provider=mock_provider, prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry, safety_guard=mock_safety,
        max_turns=2,
    )

    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"cmd": "ls"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
        ),
    ]

    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("do something", ctx)

    assert resp.content == "Done."
    mock_tool_registry.execute.assert_called_once()
