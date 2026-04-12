from breadmind.hooks import HookDecision, HookEvent, HookPayload
from breadmind.hooks.chain import HookChain
from breadmind.hooks.handler import PythonHook
from breadmind.hooks.trace import get_trace_buffer


async def test_chain_records_trace_entry_per_hook():
    buf = get_trace_buffer()
    before = len(buf.recent(1000))

    chain = HookChain(
        event=HookEvent.PRE_TOOL_USE,
        handlers=[
            PythonHook(
                name="pass",
                event=HookEvent.PRE_TOOL_USE,
                handler=lambda p: HookDecision.proceed(),
            ),
            PythonHook(
                name="modify",
                event=HookEvent.PRE_TOOL_USE,
                handler=lambda p: HookDecision.modify(note="ok"),
            ),
        ],
    )
    await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))

    entries = buf.recent(1000)
    new_entries = entries[before:]
    assert len(new_entries) == 2
    names = [e.hook_id for e in new_entries]
    assert "pass" in names and "modify" in names
    decisions = [e.decision for e in new_entries]
    assert "proceed" in decisions and "modify" in decisions


async def test_chain_trace_captures_block_reason():
    buf = get_trace_buffer()
    before = len(buf.recent(1000))

    chain = HookChain(
        event=HookEvent.PRE_TOOL_USE,
        handlers=[
            PythonHook(
                name="deny",
                event=HookEvent.PRE_TOOL_USE,
                handler=lambda p: HookDecision.block("forbidden"),
            ),
        ],
    )
    await chain.run(HookPayload(event=HookEvent.PRE_TOOL_USE))

    new_entries = buf.recent(1000)[before:]
    assert len(new_entries) == 1
    assert new_entries[0].decision == "block"
    assert new_entries[0].reason == "forbidden"
