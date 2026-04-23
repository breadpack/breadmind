"""Tests for ``JobTracker`` DB write-through (Task 5).

``JobTracker.bind_store()`` attaches a :class:`JobStore` so every mutation
(``create_job`` / ``set_phases`` / ``start_phase`` / ``complete_phase`` /
``complete_job`` / ``cancel_job``) schedules a fire-and-forget
``ensure_future`` DB write. The in-memory state change happens
synchronously; the persistence is eventually consistent.

These tests rely on the existing ``test_db`` fixture (from
``tests/conftest.py``) which has migration 007 already applied.
"""
from __future__ import annotations

import asyncio

import pytest

from breadmind.coding.job_store import JobStore
from breadmind.coding.job_tracker import JobTracker
from breadmind.coding.log_buffer import LogBuffer


@pytest.fixture(autouse=True)
async def _isolate_coding_tables(test_db):
    """Each test starts with an empty coding_jobs table (cascade clears phases)."""
    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM coding_jobs")
    yield


async def test_tracker_write_through_create(test_db) -> None:
    store = JobStore(test_db)
    tracker = JobTracker()
    tracker.bind_store(store)

    tracker.create_job(
        "j1", "p", "claude", "hello",
        user="alice", channel="#dev",
    )
    await asyncio.sleep(0.05)  # let ensure_future run

    row = await store.get_job("j1")
    assert row is not None
    assert row["project"] == "p"
    assert row["user_name"] == "alice"
    assert row["channel"] == "#dev"


async def test_tracker_write_through_phases_and_complete(test_db) -> None:
    store = JobStore(test_db)
    tracker = JobTracker()
    tracker.bind_store(store)
    tracker.create_job("j2", "p", "c", "x", user="", channel="")
    tracker.set_phases(
        "j2",
        [{"step": 1, "title": "a"}, {"step": 2, "title": "b"}],
    )
    tracker.start_phase("j2", 1)
    tracker.complete_phase(
        "j2", 1, success=True, output="done", files_changed=["x.py"],
    )
    tracker.complete_job("j2", success=True, session_id="sid")
    await asyncio.sleep(0.1)

    row = await store.get_job("j2")
    assert row["status"] == "completed"
    assert row["session_id"] == "sid"
    assert row["total_phases"] == 2
    phases = await store.list_phases("j2")
    assert phases[0]["status"] == "completed"
    assert phases[0]["files_changed"] == ["x.py"]


async def test_tracker_append_log(test_db) -> None:
    store = JobStore(test_db)
    tracker = JobTracker()
    tracker.bind_store(store)

    buffer = LogBuffer(
        flush_fn=JobTracker.make_default_flush(store),
        size_threshold=2,
        time_threshold_s=0.05,
    )
    tracker.bind_log_buffer(buffer)

    tracker.create_job("j3", "p", "c", "x", user="", channel="")
    tracker.set_phases("j3", [{"step": 1, "title": "a"}])
    tracker.start_phase("j3", 1)

    emitted: list[tuple] = []

    async def log_listener(job_id, step, line_no, ts, text):
        emitted.append((job_id, step, line_no, text))

    tracker.add_log_listener(log_listener)

    for i in range(1, 4):
        await tracker.append_log("j3", 1, f"line {i}")

    tracker.complete_phase("j3", 1, success=True)
    await asyncio.sleep(0.15)

    rows = await store.list_logs("j3", step=1, limit=10)
    assert [r["text"] for r in rows] == ["line 1", "line 2", "line 3"]
    assert [r["line_no"] for r in rows] == [1, 2, 3]
    assert len(emitted) == 3


async def test_code_delegate_propagates_user_channel(test_db, monkeypatch) -> None:
    """Task 9: ``_register_job_for_delegation`` must forward ``user``/``channel``.

    The helper is the single entry point used by ``code_delegate`` to register
    a job with ``JobTracker``. Replacing the module-level ``JobTracker``
    reference with a factory lambda verifies the helper doesn't hard-code
    ``.get_instance()`` in a way that would break test injection.
    """
    from breadmind.coding import tool as ct

    tracker = JobTracker()
    store = JobStore(test_db)
    tracker.bind_store(store)

    # Replace the class reference with a factory returning our test tracker.
    # The helper falls back to ``JobTracker()`` when ``get_instance`` is absent.
    monkeypatch.setattr(ct, "JobTracker", lambda: tracker, raising=False)

    ct._register_job_for_delegation(
        job_id="jD", project="p", agent="c", prompt="x",
        user="alice", channel="#ops",
    )
    await asyncio.sleep(0.05)

    row = await store.get_job("jD")
    assert row is not None
    assert row["user_name"] == "alice"
    assert row["channel"] == "#ops"
