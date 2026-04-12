"""Tests for hook handler types: COMMAND, PROMPT, AGENT."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.core.tool_hooks import (
    HookHandlerType,
    ToolHookConfig,
    ToolHookResult,
    ToolHookRunner,
    ToolHookType,
)


@pytest.fixture
def runner():
    return ToolHookRunner()


# ── COMMAND type (backward compat) ───────────────────────────────


async def test_command_hook_continues(runner):
    """Default COMMAND handler_type works as before."""

    def handler(tool_name, args):
        return ToolHookResult(action="continue", additional_context="checked")

    hook = ToolHookConfig(
        name="cmd-check",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=handler,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "ls"})
    assert result.action == "continue"
    assert result.additional_context == "checked"


async def test_command_hook_blocks(runner):
    """COMMAND hook can block execution."""

    def handler(tool_name, args):
        return ToolHookResult(action="block", block_reason="dangerous")

    hook = ToolHookConfig(
        name="blocker",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=handler,
        handler_type=HookHandlerType.COMMAND,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "rm -rf /"})
    assert result.action == "block"
    assert "dangerous" in result.block_reason


# ── PROMPT type ──────────────────────────────────────────────────


async def test_prompt_hook_allow(runner):
    """PROMPT hook with LLM responding 'allow' should continue."""
    llm = AsyncMock(return_value="Allow - this is safe")

    hook = ToolHookConfig(
        name="prompt-safety",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="shell_*",
        handler=lambda *a: None,  # not used for PROMPT type
        handler_type=HookHandlerType.PROMPT,
        prompt_template="Is this safe? Arguments: $ARGUMENTS",
        llm_provider=llm,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "echo hi"})
    assert result.action == "continue"
    # LLM was called with the substituted template
    call_arg = llm.call_args[0][0]
    assert '"cmd": "echo hi"' in call_arg


async def test_prompt_hook_deny(runner):
    """PROMPT hook with LLM responding 'deny' should block."""
    llm = AsyncMock(return_value="Deny - this command is destructive")

    hook = ToolHookConfig(
        name="prompt-deny",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=lambda *a: None,
        handler_type=HookHandlerType.PROMPT,
        prompt_template="Check: $ARGUMENTS",
        llm_provider=llm,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "rm -rf /"})
    assert result.action == "block"
    assert "denied" in result.block_reason.lower()


async def test_prompt_hook_block_response(runner):
    """PROMPT hook recognizes 'block' prefix as denial."""
    llm = AsyncMock(return_value="Block: not allowed")

    hook = ToolHookConfig(
        name="prompt-block",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=lambda *a: None,
        handler_type=HookHandlerType.PROMPT,
        prompt_template="$ARGUMENTS",
        llm_provider=llm,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("any_tool", {})
    assert result.action == "block"


async def test_prompt_hook_no_provider_skips(runner):
    """PROMPT hook without llm_provider should gracefully skip."""
    hook = ToolHookConfig(
        name="no-provider",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=lambda *a: None,
        handler_type=HookHandlerType.PROMPT,
        prompt_template="Check: $ARGUMENTS",
        llm_provider=None,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("tool", {"x": 1})
    assert result.action == "continue"


async def test_prompt_hook_llm_error_continues(runner):
    """If LLM call raises, hook gracefully continues."""
    llm = AsyncMock(side_effect=RuntimeError("API down"))

    hook = ToolHookConfig(
        name="failing-llm",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=lambda *a: None,
        handler_type=HookHandlerType.PROMPT,
        prompt_template="$ARGUMENTS",
        llm_provider=llm,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("tool", {})
    # Should not raise, returns default continue
    assert result.action == "continue"


# ── AGENT type ───────────────────────────────────────────────────


async def test_agent_hook_with_file_reader(runner):
    """AGENT hook receives file_reader kwarg and returns structured result."""

    async def agent_handler(tool_name, args, *, file_reader=None):
        if file_reader:
            content = await file_reader("pyproject.toml")
            if "breadmind" in content:
                return ToolHookResult(
                    action="continue",
                    additional_context="Project validated",
                )
        return ToolHookResult(action="block", block_reason="no reader")

    reader = AsyncMock(return_value="[project]\nname = 'breadmind'")

    hook = ToolHookConfig(
        name="agent-check",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=agent_handler,
        handler_type=HookHandlerType.AGENT,
        file_reader=reader,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("deploy", {"target": "prod"})
    assert result.action == "continue"
    assert "validated" in result.additional_context
    reader.assert_awaited_once_with("pyproject.toml")


async def test_agent_hook_blocks(runner):
    """AGENT hook can block tool execution."""

    async def agent_handler(tool_name, args, *, file_reader=None):
        return ToolHookResult(action="block", block_reason="Agent says no")

    hook = ToolHookConfig(
        name="agent-blocker",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=agent_handler,
        handler_type=HookHandlerType.AGENT,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("dangerous_tool", {})
    assert result.action == "block"


async def test_agent_hook_error_continues(runner):
    """AGENT hook that raises should gracefully return continue."""

    async def broken_agent(tool_name, args, *, file_reader=None):
        raise ValueError("agent crashed")

    hook = ToolHookConfig(
        name="broken-agent",
        hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*",
        handler=broken_agent,
        handler_type=HookHandlerType.AGENT,
    )
    runner.register(hook)
    result = await runner.run_pre_hooks("tool", {})
    assert result.action == "continue"


# ── Mixed hooks ──────────────────────────────────────────────────


async def test_mixed_hook_types_priority(runner):
    """COMMAND, PROMPT, and AGENT hooks can coexist with priority ordering."""
    call_order = []

    def cmd_hook(tool_name, args):
        call_order.append("command")
        return ToolHookResult()

    async def agent_hook(tool_name, args, *, file_reader=None):
        call_order.append("agent")
        return ToolHookResult()

    llm = AsyncMock(return_value="Allow")

    runner.register(ToolHookConfig(
        name="cmd", hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*", handler=cmd_hook,
        handler_type=HookHandlerType.COMMAND, priority=10,
    ))
    runner.register(ToolHookConfig(
        name="agent", hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*", handler=agent_hook,
        handler_type=HookHandlerType.AGENT, priority=5,
    ))
    runner.register(ToolHookConfig(
        name="prompt", hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*", handler=lambda *a: None,
        handler_type=HookHandlerType.PROMPT, priority=1,
        prompt_template="ok? $ARGUMENTS", llm_provider=llm,
    ))

    await runner.run_pre_hooks("tool", {})
    assert call_order == ["command", "agent"]  # prompt doesn't append to call_order


async def test_handler_type_enum_values():
    """HookHandlerType has the three expected values."""
    assert HookHandlerType.COMMAND.value == "command"
    assert HookHandlerType.PROMPT.value == "prompt"
    assert HookHandlerType.AGENT.value == "agent"
    assert len(HookHandlerType) == 3
