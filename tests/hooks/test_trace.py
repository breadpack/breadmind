import time

from breadmind.hooks.trace import HookTraceBuffer, HookTraceEntry


def test_ring_buffer_caps_at_max():
    buf = HookTraceBuffer(max_entries=3)
    for i in range(5):
        buf.record(HookTraceEntry(
            timestamp=time.time(), hook_id=f"h{i}", event="pre_tool_use",
            decision="proceed", duration_ms=1.0,
        ))
    entries = buf.recent(10)
    assert len(entries) == 3
    assert [e.hook_id for e in entries] == ["h2", "h3", "h4"]


def test_stats_by_hook_id():
    buf = HookTraceBuffer(max_entries=100)
    buf.record(HookTraceEntry(
        timestamp=1.0, hook_id="a", event="pre_tool_use",
        decision="proceed", duration_ms=10.0,
    ))
    buf.record(HookTraceEntry(
        timestamp=2.0, hook_id="a", event="pre_tool_use",
        decision="block", duration_ms=20.0,
    ))
    buf.record(HookTraceEntry(
        timestamp=3.0, hook_id="b", event="pre_tool_use",
        decision="proceed", duration_ms=5.0,
    ))
    stats = buf.stats()
    a_stats = next(s for s in stats if s["hook_id"] == "a")
    assert a_stats["total"] == 2
    assert a_stats["avg_duration_ms"] == 15.0
    assert a_stats["block_count"] == 1


def test_filter_by_event():
    buf = HookTraceBuffer(max_entries=100)
    buf.record(HookTraceEntry(
        timestamp=1.0, hook_id="a", event="pre_tool_use",
        decision="proceed", duration_ms=1.0,
    ))
    buf.record(HookTraceEntry(
        timestamp=2.0, hook_id="b", event="llm_request",
        decision="proceed", duration_ms=1.0,
    ))
    out = buf.recent(10, event="pre_tool_use")
    assert len(out) == 1
    assert out[0].hook_id == "a"
