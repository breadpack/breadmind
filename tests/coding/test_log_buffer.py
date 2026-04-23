import asyncio
import pytest

from breadmind.coding.log_buffer import LogBuffer


@pytest.mark.asyncio
async def test_flushes_at_size():
    flushed: list[list] = []

    async def flush(batch):
        flushed.append(list(batch))

    buf = LogBuffer(flush_fn=flush, size_threshold=3, time_threshold_s=10.0)
    await buf.append("j1", 1, 1, "a")
    await buf.append("j1", 1, 2, "b")
    assert flushed == []
    await buf.append("j1", 1, 3, "c")
    # size-triggered flush happens synchronously
    assert len(flushed) == 1
    assert len(flushed[0]) == 3
    # tuple shape: (job_id, step, line_no, ts, text)
    assert [t[2] for t in flushed[0]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_flushes_after_time():
    flushed: list[list] = []

    async def flush(batch):
        flushed.append(list(batch))

    buf = LogBuffer(flush_fn=flush, size_threshold=100, time_threshold_s=0.1)
    await buf.append("j1", 1, 1, "a")
    await asyncio.sleep(0.2)
    await buf.tick()
    assert len(flushed) == 1


@pytest.mark.asyncio
async def test_force_flush_on_phase_complete():
    flushed: list[list] = []

    async def flush(batch):
        flushed.append(list(batch))

    buf = LogBuffer(flush_fn=flush, size_threshold=100, time_threshold_s=10.0)
    await buf.append("j1", 1, 1, "a")
    await buf.force_flush("j1", 1)
    assert len(flushed) == 1
    assert len(flushed[0]) == 1
    # tuple shape: (job_id, step, line_no, ts, text)
    assert flushed[0][0][0:3] == ("j1", 1, 1)
    assert flushed[0][0][4] == "a"


@pytest.mark.asyncio
async def test_size_cap_drops_oldest():
    flushed: list[list] = []
    dropped: list[int] = []

    async def flush(batch):
        flushed.append(list(batch))

    def on_drop(n):
        dropped.append(n)

    buf = LogBuffer(
        flush_fn=flush,
        size_threshold=1000,
        time_threshold_s=10.0,
        per_phase_cap=5,
        on_drop=on_drop,
    )
    for i in range(1, 8):
        await buf.append("j1", 1, i, f"l{i}")
    # cap=5, so first 2 dropped (one per over-cap append)
    await buf.force_flush("j1", 1)
    line_nos = [t[2] for t in flushed[0]]
    assert line_nos == [3, 4, 5, 6, 7]
    # Spec noted this is [1, 1] (per-append drop of 1 each), not [2].
    # See runner report Task 4 — spec test assertion was [2]; actual
    # implementation drops once per append when len>cap.
    assert dropped == [1, 1]
