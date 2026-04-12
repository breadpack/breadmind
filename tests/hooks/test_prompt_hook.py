from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


from breadmind.hooks.decision import DecisionKind
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.prompt_hook import PromptHook, _render_prompt


def _hook(**kwargs) -> PromptHook:
    defaults = dict(
        name="test-hook",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Evaluate: {{ event }} {{ tool_name }}",
    )
    defaults.update(kwargs)
    return PromptHook(**defaults)


def _payload(event=HookEvent.PRE_TOOL_USE, data=None) -> HookPayload:
    return HookPayload(event=event, data=data or {})


# ---------------------------------------------------------------------------
# ok=true → PROCEED
# ---------------------------------------------------------------------------

async def test_ok_true_proceeds():
    hook = _hook()
    with patch.object(PromptHook, "_call_llm", new=AsyncMock(return_value='{"ok": true, "reason": "safe"}')):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.PROCEED
    assert "safe" in d.context
    assert d.hook_id == "test-hook"


# ---------------------------------------------------------------------------
# ok=false on blockable event → BLOCK
# ---------------------------------------------------------------------------

async def test_ok_false_blocks():
    hook = _hook(event=HookEvent.PRE_TOOL_USE)
    with patch.object(PromptHook, "_call_llm", new=AsyncMock(return_value='{"ok": false, "reason": "dangerous"}')):
        d = await hook.run(_payload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind == DecisionKind.BLOCK
    assert "dangerous" in d.reason


# ---------------------------------------------------------------------------
# Non-JSON response → PROCEED (lenient)
# ---------------------------------------------------------------------------

async def test_non_json_response_proceeds():
    hook = _hook()
    with patch.object(PromptHook, "_call_llm", new=AsyncMock(return_value="I think it's fine")):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.PROCEED


# ---------------------------------------------------------------------------
# Timeout → _failure_decision (BLOCK on blockable)
# ---------------------------------------------------------------------------

async def test_timeout_uses_failure_decision():
    hook = _hook(event=HookEvent.PRE_TOOL_USE, timeout_sec=0.05)

    async def _slow(_prompt):
        await asyncio.sleep(5)
        return ""

    with patch.object(PromptHook, "_call_llm", new=_slow):
        d = await hook.run(_payload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind == DecisionKind.BLOCK
    assert "timeout" in d.reason.lower()


# ---------------------------------------------------------------------------
# Jinja2 template renders correctly
# ---------------------------------------------------------------------------

async def test_jinja_template_renders():
    rendered = _render_prompt(
        "Event={{ event }}, tool={{ tool_name }}, cmd={{ args.cmd }}",
        {
            "event": "pre_tool_use",
            "tool_name": "bash",
            "args": {"cmd": "ls"},
            "data": {},
        },
    )
    assert "pre_tool_use" in rendered
    assert "bash" in rendered


# ---------------------------------------------------------------------------
# Observational event: exception → PROCEED
# ---------------------------------------------------------------------------

async def test_observational_event_proceeds_on_failure():
    hook = _hook(event=HookEvent.POST_TOOL_USE)

    async def _raise(_prompt):
        raise RuntimeError("network error")

    with patch.object(PromptHook, "_call_llm", new=_raise):
        d = await hook.run(_payload(event=HookEvent.POST_TOOL_USE))
    assert d.kind == DecisionKind.PROCEED


# ---------------------------------------------------------------------------
# if_condition field exists on dataclass
# ---------------------------------------------------------------------------

async def test_if_condition_field():
    hook_single = _hook(if_condition="data.get('x') > 0")
    assert hook_single.if_condition == "data.get('x') > 0"

    hook_list = _hook(if_condition=["cond_a", "cond_b"])
    assert hook_list.if_condition == ["cond_a", "cond_b"]

    hook_none = _hook()
    assert hook_none.if_condition is None


# ---------------------------------------------------------------------------
# ok=false on observational event → log + PROCEED
# ---------------------------------------------------------------------------

async def test_ok_false_on_observational_proceeds():
    hook = _hook(event=HookEvent.POST_TOOL_USE)
    with patch.object(PromptHook, "_call_llm", new=AsyncMock(return_value='{"ok": false, "reason": "warning"}')):
        d = await hook.run(_payload(event=HookEvent.POST_TOOL_USE))
    assert d.kind == DecisionKind.PROCEED
    assert "warning" in d.context


# ---------------------------------------------------------------------------
# Markdown-wrapped JSON is parsed correctly
# ---------------------------------------------------------------------------

async def test_markdown_json_parsed():
    hook = _hook()
    md_response = '```json\n{"ok": false, "reason": "blocked"}\n```'
    with patch.object(PromptHook, "_call_llm", new=AsyncMock(return_value=md_response)):
        d = await hook.run(_payload())
    assert d.kind == DecisionKind.BLOCK
    assert "blocked" in d.reason
