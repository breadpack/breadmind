from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.chain import HookChain
from breadmind.hooks.handler import PythonHook


def _mk(name, decision_fn, priority=0, event=HookEvent.PRE_TOOL_USE):
    return PythonHook(
        name=name, event=event, handler=decision_fn, priority=priority,
    )


async def test_empty_chain_proceeds():
    chain = HookChain(event=HookEvent.PRE_TOOL_USE)
    d, payload = await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind.value == "proceed"


async def test_priority_order():
    order = []
    h_low = _mk("low", lambda p: (order.append("low"), HookDecision.proceed())[1], 0)
    h_high = _mk("high", lambda p: (order.append("high"), HookDecision.proceed())[1], 100)
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[h_low, h_high])
    await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert order == ["high", "low"]


async def test_block_early_terminates():
    calls = []
    h1 = _mk("h1", lambda p: (calls.append("h1"), HookDecision.block("stop"))[1], 10)
    h2 = _mk("h2", lambda p: (calls.append("h2"), HookDecision.proceed())[1], 5)
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[h1, h2])
    d, _ = await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind.value == "block"
    assert calls == ["h1"]


async def test_modify_accumulates_and_next_sees_patched():
    seen = {}

    def h1(p):
        return HookDecision.modify(a=1)

    def h2(p):
        seen.update(p.data)
        return HookDecision.modify(b=2)

    chain = HookChain(
        event=HookEvent.PRE_TOOL_USE,
        handlers=[_mk("h1", h1, 10), _mk("h2", h2, 5)],
    )
    d, payload = await chain.run(
        HookPayload(event=HookEvent.PRE_TOOL_USE, data={"x": 0}),
    )
    assert d.kind.value == "modify"
    assert payload.data == {"x": 0, "a": 1, "b": 2}
    assert seen == {"x": 0, "a": 1}


async def test_reply_short_circuits():
    h1 = _mk("h1", lambda p: HookDecision.reply("hit"), 10)
    h2 = _mk("h2", lambda p: HookDecision.proceed(), 5)
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[h1, h2])
    d, _ = await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind.value == "reply"
    assert d.reply == "hit"


async def test_observational_event_ignores_block():
    h = _mk(
        "h", lambda p: HookDecision.block("ignored"), 10,
        event=HookEvent.SESSION_START,
    )
    chain = HookChain(event=HookEvent.SESSION_START, handlers=[h])
    d, _ = await chain.run(HookPayload(event=HookEvent.SESSION_START))
    assert d.kind.value == "proceed"
