from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.chain import HookChain, MAX_REROUTE_DEPTH
from breadmind.hooks.handler import PythonHook


def _mk(name, fn, priority=0):
    return PythonHook(
        name=name, event=HookEvent.PRE_TOOL_USE, handler=fn, priority=priority,
    )


async def test_max_depth_exceeded_ignores_reroute():
    h = _mk("r", lambda p: HookDecision.reroute("other"))
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[h])
    payload = HookPayload(event=HookEvent.PRE_TOOL_USE, depth=MAX_REROUTE_DEPTH)
    d, _ = await chain.run(payload)
    assert d.kind.value == "proceed"


async def test_visited_target_ignores_reroute():
    h = _mk("r", lambda p: HookDecision.reroute("already"))
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[h])
    payload = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        visited={"already"},
    )
    d, _ = await chain.run(payload)
    assert d.kind.value == "proceed"
