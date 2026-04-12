from breadmind.core.events import EventBus
from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook


async def test_run_hook_chain_with_no_hooks_proceeds(fresh_bus):
    d = await fresh_bus.run_hook_chain(
        HookEvent.PRE_TOOL_USE,
        HookPayload(event=HookEvent.PRE_TOOL_USE),
    )
    assert d.kind.value == "proceed"


async def test_register_and_run(fresh_bus):
    hook = PythonHook(
        name="block-all",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.block("nope"),
    )
    hook_id = fresh_bus.register_hook(HookEvent.PRE_TOOL_USE, hook)
    assert hook_id

    d = await fresh_bus.run_hook_chain(
        HookEvent.PRE_TOOL_USE,
        HookPayload(event=HookEvent.PRE_TOOL_USE),
    )
    assert d.kind.value == "block"


async def test_unregister(fresh_bus):
    hook = PythonHook(
        name="blocker",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.block("nope"),
    )
    hid = fresh_bus.register_hook(HookEvent.PRE_TOOL_USE, hook)
    assert fresh_bus.unregister_hook(hid) is True
    d = await fresh_bus.run_hook_chain(
        HookEvent.PRE_TOOL_USE,
        HookPayload(event=HookEvent.PRE_TOOL_USE),
    )
    assert d.kind.value == "proceed"


async def test_listeners_still_fire_alongside_hooks(fresh_bus):
    seen = []
    fresh_bus.on("pre_tool_use", lambda data: seen.append(data))

    hook = PythonHook(
        name="pass",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.proceed(),
    )
    fresh_bus.register_hook(HookEvent.PRE_TOOL_USE, hook)

    await fresh_bus.run_hook_chain(
        HookEvent.PRE_TOOL_USE,
        HookPayload(event=HookEvent.PRE_TOOL_USE, data={"tool_name": "x"}),
    )
    assert seen and seen[0] == {"tool_name": "x"}
