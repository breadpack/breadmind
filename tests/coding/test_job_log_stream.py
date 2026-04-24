"""JobLogStream — listeners + line counter + buffer integration."""
from __future__ import annotations

import asyncio
from datetime import datetime

from breadmind.coding.job_log_stream import JobLogStream


class _StubBuffer:
    def __init__(self) -> None:
        self.appended: list[tuple[str, int, int, str]] = []
        self.flushed: list[tuple[str, int]] = []

    async def append(self, job_id, step, line_no, text):
        self.appended.append((job_id, step, line_no, text))

    async def force_flush(self, job_id, step):
        self.flushed.append((job_id, step))


async def test_line_no_monotonic_per_phase() -> None:
    stream = JobLogStream()
    buf = _StubBuffer()
    stream.bind_buffer(buf)
    await stream.append("j1", 1, "first")
    await stream.append("j1", 1, "second")
    await stream.append("j1", 2, "phase2-first")
    nums = [a[2] for a in buf.appended]
    assert nums == [1, 2, 1]


async def test_listeners_fire_on_append() -> None:
    stream = JobLogStream()
    received: list[tuple[str, int, int, datetime, str]] = []

    async def cb(job_id, step, line_no, ts, text):
        received.append((job_id, step, line_no, ts, text))

    stream.add_listener(cb)
    await stream.append("j1", 1, "hello")
    await asyncio.sleep(0.02)  # ensure_future drains
    assert len(received) == 1
    assert received[0][0:3] == ("j1", 1, 1)
    assert received[0][4] == "hello"


async def test_evict_job_counters_clears_all_phases() -> None:
    stream = JobLogStream()
    stream.reset_phase_counter("j1", 1)
    stream.reset_phase_counter("j1", 2)
    stream.reset_phase_counter("j2", 1)
    stream.evict_job_counters("j1")
    # j2 untouched; j1 entries gone
    assert (("j1", 1) not in stream._line_counters)
    assert (("j1", 2) not in stream._line_counters)
    assert (("j2", 1) in stream._line_counters)


async def test_force_flush_phase_no_buffer_silent() -> None:
    """force_flush_phase must be safe before bind_buffer."""
    stream = JobLogStream()
    stream.force_flush_phase("j1", 1)  # no exception


async def test_force_flush_phase_with_buffer_signals() -> None:
    stream = JobLogStream()
    buf = _StubBuffer()
    stream.bind_buffer(buf)
    stream.force_flush_phase("j1", 1)
    await asyncio.sleep(0.02)
    assert buf.flushed == [("j1", 1)]


async def test_buffer_unbound_listener_only() -> None:
    stream = JobLogStream()
    received = []

    async def cb(*args):
        received.append(args)

    stream.add_listener(cb)
    await stream.append("j1", 1, "x")
    await asyncio.sleep(0.02)
    assert len(received) == 1
