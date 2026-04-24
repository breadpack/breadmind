"""JobDbWriter — Task 2 skeleton: helper methods enqueue store coros."""
from __future__ import annotations

import asyncio

from breadmind.coding.job_db_writer import JobDbWriter
from breadmind.coding.job_models import JobInfo, JobStatus


class _StubStore:
    """Records every coro invocation so we can assert ordering + payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def insert_job(self, **kw):
        self.calls.append(("insert_job", kw))

    async def update_job(self, **kw):
        self.calls.append(("update_job", kw))

    async def insert_phases(self, job_id, phases):
        self.calls.append(("insert_phases", {"job_id": job_id, "phases": phases}))

    async def update_phase(self, **kw):
        self.calls.append(("update_phase", kw))


async def test_insert_job_enqueues_store_call() -> None:
    store = _StubStore()
    writer = JobDbWriter(store)
    job = JobInfo(
        job_id="j1", project="p", agent="claude", prompt="hi",
        status=JobStatus.PENDING, started_at=1000.0,
        user="alice", channel="#dev",
    )
    writer.insert_job(job)
    await asyncio.sleep(0.05)
    assert any(name == "insert_job" for name, _ in store.calls)
    payload = next(kw for name, kw in store.calls if name == "insert_job")
    assert payload["job_id"] == "j1"
    assert payload["user_name"] == "alice"
    assert payload["channel"] == "#dev"


async def test_update_job_status_enqueues_store_call() -> None:
    store = _StubStore()
    writer = JobDbWriter(store)
    job = JobInfo(job_id="j2", project="p", agent="c", prompt="x",
                  status=JobStatus.RUNNING, started_at=1000.0)
    writer.update_job_status(job)
    await asyncio.sleep(0.05)
    assert ("update_job", {"job_id": "j2", "status": "running"}) in [
        (n, k) for n, k in store.calls if n == "update_job"
    ]


async def test_no_running_loop_silently_drops() -> None:
    """schedule() called with no running loop must not raise + must not warn-leak."""
    store = _StubStore()
    writer = JobDbWriter(store)

    async def _coro():
        return None

    coro = _coro()
    # Calling from sync context simulates the offline-test path.
    # We call it inside an event-loop-less helper:
    import threading
    def _call():
        writer.schedule(coro)
    t = threading.Thread(target=_call)
    t.start()
    t.join()
    # No assertion on store.calls — coro was closed; the contract is "doesn't raise".
