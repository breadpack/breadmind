"""Integration tests for conditional filtering in HookChain.

Tests verify that if_condition on PythonHook / ShellHook causes the
chain to skip non-matching handlers and run matching ones.
"""
from __future__ import annotations

from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.chain import HookChain
from breadmind.hooks.handler import PythonHook, ShellHook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_condition_skips_non_matching_handler():
    """PythonHook with if_condition='Bash(rm *)' must NOT fire when tool_name='Read'."""
    fired = []

    hook = PythonHook(
        name="dangerous-bash-hook",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: (fired.append(True), HookDecision.block("blocked"))[1],
        if_condition="Bash(rm *)",
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[hook])
    payload = _payload(tool_name="Read", tool_input="/etc/passwd")

    d, _ = await chain.run(payload)

    assert fired == [], "Handler should have been skipped"
    assert d.kind.value == "proceed", "Chain should proceed when handler is skipped"


async def test_condition_fires_matching_handler():
    """PythonHook with if_condition='Bash(rm *)' SHOULD fire when tool matches."""
    fired = []

    hook = PythonHook(
        name="dangerous-bash-hook",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: (fired.append(True), HookDecision.block("blocked rm"))[1],
        if_condition="Bash(rm *)",
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[hook])
    payload = _payload(tool_name="Bash", tool_input="rm -rf /tmp")

    d, _ = await chain.run(payload)

    assert fired == [True], "Handler should have fired"
    assert d.kind.value == "block"
    assert "blocked rm" in d.reason


async def test_no_condition_always_fires():
    """A hook without if_condition fires for any payload."""
    fired = []

    hook = PythonHook(
        name="always-hook",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: (fired.append(True), HookDecision.proceed())[1],
        # no if_condition — defaults to None
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[hook])

    for tool in ("Read", "Write", "Bash", "Edit"):
        fired.clear()
        await chain.run(_payload(tool_name=tool, tool_input="something"))
        assert fired == [True], f"Hook should have fired for tool '{tool}'"


async def test_shell_hook_with_condition():
    """ShellHook dataclass must accept and store if_condition."""
    hook = ShellHook(
        name="shell-cond-hook",
        event=HookEvent.PRE_TOOL_USE,
        command="exit 0",
        if_condition="Bash(rm *)",
    )
    assert hook.if_condition == "Bash(rm *)"


async def test_condition_list_or_semantics():
    """if_condition as a list uses OR semantics — fires if any pattern matches."""
    fired = []

    hook = PythonHook(
        name="multi-cond-hook",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: (fired.append(p.data.get("tool_name")), HookDecision.proceed())[1],
        if_condition=["Bash(rm *)", "Write(*)"],
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[hook])

    # Should fire for Bash rm
    await chain.run(_payload(tool_name="Bash", tool_input="rm -rf /tmp"))
    # Should fire for Write
    await chain.run(_payload(tool_name="Write", tool_input="/tmp/file.txt"))
    # Should NOT fire for Read
    await chain.run(_payload(tool_name="Read", tool_input="/tmp/file.txt"))

    assert fired == ["Bash", "Write"], f"Unexpected fired list: {fired}"
