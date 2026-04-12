import asyncio
import pytest

from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook


async def _payload(data=None):
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data or {})


async def test_sync_handler_returning_decision():
    def h(payload):
        return HookDecision.block("nope")

    hook = PythonHook(name="t", event=HookEvent.PRE_TOOL_USE, handler=h)
    d = await hook.run(await _payload())
    assert d.kind.value == "block"
    assert d.reason == "nope"
    assert d.hook_id == "t"


async def test_async_handler():
    async def h(payload):
        return HookDecision.modify(args={"cmd": "safe"})

    hook = PythonHook(name="t", event=HookEvent.PRE_TOOL_USE, handler=h)
    d = await hook.run(await _payload({"args": {"cmd": "rm -rf /"}}))
    assert d.kind.value == "modify"
    assert d.patch == {"args": {"cmd": "safe"}}


async def test_non_decision_return_becomes_proceed():
    def h(payload):
        return None

    hook = PythonHook(name="t", event=HookEvent.PRE_TOOL_USE, handler=h)
    d = await hook.run(await _payload())
    assert d.kind.value == "proceed"


async def test_handler_exception_blocks_on_blockable_event():
    def h(payload):
        raise RuntimeError("boom")

    hook = PythonHook(name="t", event=HookEvent.PRE_TOOL_USE, handler=h)
    d = await hook.run(await _payload())
    assert d.kind.value == "block"
    assert "boom" in d.reason


async def test_handler_exception_observational_returns_proceed():
    def h(payload):
        raise RuntimeError("boom")

    hook = PythonHook(name="t", event=HookEvent.SESSION_START, handler=h)
    d = await hook.run(HookPayload(event=HookEvent.SESSION_START))
    assert d.kind.value == "proceed"


async def test_timeout_blocks():
    async def h(payload):
        await asyncio.sleep(2)
        return HookDecision.proceed()

    hook = PythonHook(
        name="t", event=HookEvent.PRE_TOOL_USE, handler=h, timeout_sec=0.05,
    )
    d = await hook.run(await _payload())
    assert d.kind.value == "block"
    assert "timeout" in d.reason.lower()
