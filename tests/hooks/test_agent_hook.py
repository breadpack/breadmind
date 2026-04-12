"""Tests for AgentHook multi-turn verifier handler."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from breadmind.hooks.agent_hook import READONLY_TOOLS, AgentHook
from breadmind.hooks.decision import DecisionKind
from breadmind.hooks.events import HookEvent, HookPayload


def _payload() -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data={"tool_name": "Bash"})


# ---------------------------------------------------------------------------
# READONLY_TOOLS preset
# ---------------------------------------------------------------------------

def test_readonly_preset():
    assert "Read" in READONLY_TOOLS
    assert "Grep" in READONLY_TOOLS
    assert "Glob" in READONLY_TOOLS


# ---------------------------------------------------------------------------
# _resolve_allowed_tools
# ---------------------------------------------------------------------------

def test_resolve_tools_readonly():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
        allowed_tools="readonly",
    )
    assert hook._resolve_allowed_tools() == READONLY_TOOLS


def test_resolve_tools_explicit_list():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
        allowed_tools=["Read", "Bash"],
    )
    assert hook._resolve_allowed_tools() == ["Read", "Bash"]


def test_resolve_tools_all():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
        allowed_tools="all",
    )
    assert hook._resolve_allowed_tools() is None


# ---------------------------------------------------------------------------
# run() — ok / block / timeout / exhausted
# ---------------------------------------------------------------------------

async def test_ok_true_proceeds():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
    )
    with patch.object(hook, "_run_agent_loop", new=AsyncMock(return_value={"ok": True, "reason": "safe"})):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.PROCEED
    assert d.hook_id == "x"


async def test_ok_false_blocks():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
    )
    with patch.object(hook, "_run_agent_loop", new=AsyncMock(return_value={"ok": False, "reason": "risky"})):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.BLOCK
    assert "risky" in d.reason
    assert d.hook_id == "x"


async def test_ok_false_non_blockable_event_proceeds():
    """ok=False on a non-blockable event should still proceed (not block)."""
    hook = AgentHook(
        name="x",
        event=HookEvent.SESSION_START,
        prompt="check",
    )
    payload = HookPayload(event=HookEvent.SESSION_START)
    with patch.object(hook, "_run_agent_loop", new=AsyncMock(return_value={"ok": False, "reason": "nope"})):
        d = await hook.run(payload)
    assert d.kind == DecisionKind.PROCEED


async def test_timeout_blocks():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
        timeout_sec=0.01,
    )

    async def _slow(*args, **kwargs):
        await asyncio.sleep(5)
        return {"ok": True, "reason": "done"}

    with patch.object(hook, "_run_agent_loop", new=_slow):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.BLOCK
    assert d.hook_id == "x"


async def test_exhausted_turns_proceeds():
    """Empty dict (no JSON extracted) → PROCEED with warning."""
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
    )
    with patch.object(hook, "_run_agent_loop", new=AsyncMock(return_value={})):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.PROCEED
    assert d.hook_id == "x"


async def test_exception_uses_failure_decision():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
    )
    with patch.object(hook, "_run_agent_loop", side_effect=RuntimeError("boom")):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.BLOCK
    assert d.hook_id == "x"


# ---------------------------------------------------------------------------
# if_condition field
# ---------------------------------------------------------------------------

def test_if_condition_field():
    hook = AgentHook(
        name="x",
        event=HookEvent.PRE_TOOL_USE,
        prompt="check",
        if_condition=["Bash(*)"],
    )
    assert hook.if_condition == ["Bash(*)"]


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

def test_extract_json_plain():
    hook = AgentHook(name="x", event=HookEvent.PRE_TOOL_USE, prompt="p")
    result = hook._extract_json('{"ok": true, "reason": "all good"}')
    assert result == {"ok": True, "reason": "all good"}


def test_extract_json_fenced_block():
    hook = AgentHook(name="x", event=HookEvent.PRE_TOOL_USE, prompt="p")
    text = '```json\n{"ok": false, "reason": "danger"}\n```'
    result = hook._extract_json(text)
    assert result == {"ok": False, "reason": "danger"}


def test_extract_json_no_json_returns_empty():
    hook = AgentHook(name="x", event=HookEvent.PRE_TOOL_USE, prompt="p")
    result = hook._extract_json("No JSON here at all.")
    assert result == {}


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

def test_default_values():
    hook = AgentHook(name="h", event=HookEvent.PRE_TOOL_USE, prompt="p")
    assert hook.priority == 0
    assert hook.tool_pattern is None
    assert hook.timeout_sec == 30.0
    assert hook.max_turns == 3
    assert hook.provider is None
    assert hook.model is None
    assert hook.allowed_tools == "readonly"
    assert hook.if_condition is None
