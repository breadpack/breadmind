from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.handler import PythonHook
from breadmind.hooks.registry import HookRegistry


class _FakeStore:
    def __init__(self, rows: list[HookOverride]):
        self._rows = rows
    async def list_all(self):
        return list(self._rows)
    async def list_by_event(self, event: str):
        return [r for r in self._rows if r.event == event]


async def test_manifest_only_registers_chain():
    reg = HookRegistry(store=_FakeStore([]))
    manifest_hook = PythonHook(
        name="inject",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.modify(note="ok"),
        priority=10,
    )
    reg.add_manifest_hook(manifest_hook)
    await reg.reload()

    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    d, _ = await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind.value == "modify"
    assert d.patch == {"note": "ok"}


async def test_db_disable_hides_manifest_hook():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="inject", source=None, event="pre_tool_use",
            type="python", tool_pattern=None, priority=0, enabled=False,
            config_json={},
        ),
    ]))
    reg.add_manifest_hook(PythonHook(
        name="inject", event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.block("x"),
    ))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    d, _ = await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))
    assert d.kind.value == "proceed"


async def test_db_override_priority_but_not_type():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="inject", source=None, event="pre_tool_use",
            type="python",
            tool_pattern=None, priority=999, enabled=True,
            config_json={},
        ),
    ]))
    base = PythonHook(
        name="inject", event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.proceed(),
        priority=1,
    )
    reg.add_manifest_hook(base)
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert chain.handlers[0].priority == 999


async def test_db_new_shell_hook_appended():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="userblock",
            source="user",
            event="pre_tool_use",
            type="shell",
            tool_pattern=None,
            priority=50,
            enabled=True,
            config_json={"command": "exit 0"},
        ),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    assert chain.handlers[0].name == "userblock"
    assert chain.handlers[0].__class__.__name__ == "ShellHook"
