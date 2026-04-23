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
