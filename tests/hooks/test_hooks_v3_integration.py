"""End-to-end: HookChain + new handler types + conditional filtering."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from breadmind.hooks.chain import HookChain
from breadmind.hooks.decision import DecisionKind, HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook, ShellHook
from breadmind.hooks.prompt_hook import PromptHook
from breadmind.hooks.agent_hook import AgentHook
from breadmind.hooks.http_hook import HttpHook


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


# ---------------------------------------------------------------------------
# Test 1: mixed_handler_chain_with_conditions
# ---------------------------------------------------------------------------

async def test_mixed_handler_chain_with_conditions():
    """PythonHook runs; PromptHook skipped due to condition mismatch."""

    async def _py_handler(payload: HookPayload) -> HookDecision:
        return HookDecision.proceed(context="py-ok")

    py_hook = PythonHook(
        name="py-hook",
        event=HookEvent.PRE_TOOL_USE,
        handler=_py_handler,
        priority=100,
    )

    prompt_hook = PromptHook(
        name="prompt-blocker",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Should I block {{ tool_name }}?",
        priority=50,
        if_condition="Bash(rm *)",
    )

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[py_hook, prompt_hook])

    with patch.object(
        PromptHook,
        "_call_llm",
        new=AsyncMock(return_value='{"ok": false, "reason": "block"}'),
    ):
        decision, _ = await chain.run(_payload(tool_name="Read"))

    assert decision.kind == DecisionKind.PROCEED
    assert "py-ok" in decision.context


# ---------------------------------------------------------------------------
# Test 2: prompt_hook_blocks_in_chain
# ---------------------------------------------------------------------------

async def test_prompt_hook_blocks_in_chain():
    """PromptHook with Bash(*) condition blocks Bash rm -rf /."""

    prompt_hook = PromptHook(
        name="bash-guard",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Evaluate: {{ tool_name }} {{ tool_input }}",
        priority=100,
        if_condition="Bash(*)",
    )

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[prompt_hook])

    with patch.object(
        PromptHook,
        "_call_llm",
        new=AsyncMock(return_value='{"ok": false, "reason": "dangerous"}'),
    ):
        decision, _ = await chain.run(
            _payload(tool_name="Bash", tool_input="rm -rf /")
        )

    assert decision.kind == DecisionKind.BLOCK
    assert "dangerous" in decision.reason


# ---------------------------------------------------------------------------
# Test 3: http_hook_in_chain
# ---------------------------------------------------------------------------

async def test_http_hook_in_chain():
    """HttpHook with Write(*) condition blocks write to secret.py."""

    http_hook = HttpHook(
        name="write-guard",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/hook",
        priority=80,
        if_condition="Write(*)",
    )

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"action": "block", "reason": "no writes"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[http_hook])

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision, _ = await chain.run(
            _payload(tool_name="Write", tool_input="secret.py")
        )

    assert decision.kind == DecisionKind.BLOCK


# ---------------------------------------------------------------------------
# Test 4: agent_hook_in_chain
# ---------------------------------------------------------------------------

async def test_agent_hook_in_chain():
    """AgentHook with no condition proceeds when agent returns ok=True."""

    agent_hook = AgentHook(
        name="agent-verifier",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Is this Bash command safe?",
        priority=90,
    )

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[agent_hook])

    with patch.object(
        AgentHook,
        "_run_agent_loop",
        new=AsyncMock(return_value={"ok": True, "reason": "safe"}),
    ):
        decision, _ = await chain.run(_payload(tool_name="Bash"))

    assert decision.kind == DecisionKind.PROCEED


# ---------------------------------------------------------------------------
# Test 5: priority_ordering_with_mixed_types
# ---------------------------------------------------------------------------

async def test_priority_ordering_with_mixed_types():
    """High-priority PromptHook blocks before low-priority PythonHook can run."""

    py_called = []

    async def _py_handler(payload: HookPayload) -> HookDecision:
        py_called.append(True)
        return HookDecision.proceed(context="py-ran")

    py_hook = PythonHook(
        name="py-low",
        event=HookEvent.PRE_TOOL_USE,
        handler=_py_handler,
        priority=10,
    )

    prompt_hook = PromptHook(
        name="prompt-high",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Check: {{ tool_name }}",
        priority=100,
    )

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[py_hook, prompt_hook])

    with patch.object(
        PromptHook,
        "_call_llm",
        new=AsyncMock(return_value='{"ok": false, "reason": "nope"}'),
    ):
        decision, _ = await chain.run(_payload(tool_name="Bash"))

    assert decision.kind == DecisionKind.BLOCK
    assert "nope" in decision.reason
    # PythonHook never ran because PromptHook blocked first
    assert not py_called


# ---------------------------------------------------------------------------
# Test 6: or_condition_with_multiple_patterns
# ---------------------------------------------------------------------------

async def test_or_condition_with_multiple_patterns():
    """PythonHook with OR condition fires on Write(*.env) and Bash(rm *) but not Read."""

    async def _block_handler(payload: HookPayload) -> HookDecision:
        return HookDecision.block("matched condition")

    hook = PythonHook(
        name="multi-cond",
        event=HookEvent.PRE_TOOL_USE,
        handler=_block_handler,
        priority=50,
        if_condition=["Bash(rm *)", "Write(*.env)"],
    )

    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[hook])

    # Read(x.py) → condition doesn't match → PROCEED
    d1, _ = await chain.run(_payload(tool_name="Read", tool_input="x.py"))
    assert d1.kind == DecisionKind.PROCEED

    # Write(.env) → matches Write(*.env) → BLOCK
    d2, _ = await chain.run(_payload(tool_name="Write", tool_input=".env"))
    assert d2.kind == DecisionKind.BLOCK

    # Bash(rm -rf /) → matches Bash(rm *) → BLOCK
    d3, _ = await chain.run(_payload(tool_name="Bash", tool_input="rm -rf /"))
    assert d3.kind == DecisionKind.BLOCK
