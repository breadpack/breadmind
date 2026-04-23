"""Tests for ``JobStore`` — CRUD over ``coding_jobs`` / ``coding_phases``.

The shared ``test_db`` fixture (``tests/conftest.py``) already runs
``Migrator.upgrade("head")``, which includes migration 007 on this
branch, so the schema under test is in place.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from breadmind.coding.job_store import JobStore


@pytest.fixture
def store(test_db) -> JobStore:
    return JobStore(test_db)


@pytest.fixture(autouse=True)
async def _isolate_coding_tables(test_db):
    """Ensure each test starts with an empty coding_jobs table.

    Cascade deletes propagate to coding_phases / coding_phase_logs,
    so a single delete is sufficient.
    """
    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM coding_jobs")
    yield


async def test_insert_and_fetch_job(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1",
        project="p",
        agent="claude",
        prompt="hello",
        user_name="alice",
        channel="#dev",
        started_at=datetime.now(timezone.utc),
        status="pending",
    )
    row = await store.get_job("j1")
    assert row is not None
    assert row["project"] == "p"
    assert row["user_name"] == "alice"
    assert row["channel"] == "#dev"
    assert row["status"] == "pending"


async def test_get_job_missing_returns_none(store: JobStore) -> None:
    assert await store.get_job("does-not-exist") is None


async def test_insert_job_is_idempotent(store: JobStore) -> None:
    started = datetime.now(timezone.utc)
    for _ in range(2):
        await store.insert_job(
            job_id="j1",
            project="p",
            agent="c",
            prompt="x",
            user_name="alice",
            channel="",
            started_at=started,
            status="pending",
        )
    rows = await store.list_jobs(limit=10)
    assert len(rows) == 1


async def test_update_job_status(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1",
        project="p",
        agent="c",
        prompt="x",
        user_name="",
        channel="",
        started_at=datetime.now(timezone.utc),
        status="pending",
    )
    await store.update_job(
        job_id="j1",
        status="completed",
        finished_at=datetime.now(timezone.utc),
        duration_seconds=42.0,
        session_id="sess",
        error="",
    )
    row = await store.get_job("j1")
    assert row["status"] == "completed"
    assert row["duration_seconds"] == 42.0
    assert row["session_id"] == "sess"
    assert row["finished_at"] is not None


async def test_update_job_preserves_unset_fields(store: JobStore) -> None:
    """``error`` / ``session_id`` use empty-string as sentinel and must not
    overwrite previously-set values when omitted."""
    await store.insert_job(
        job_id="j1",
        project="p",
        agent="c",
        prompt="x",
        user_name="",
        channel="",
        started_at=datetime.now(timezone.utc),
        status="pending",
    )
    await store.update_job(
        job_id="j1",
        status="failed",
        error="boom",
        session_id="sess",
    )
    # Second update flips status again but doesn't re-supply error.
    await store.update_job(job_id="j1", status="completed")
    row = await store.get_job("j1")
    assert row["status"] == "completed"
    assert row["error"] == "boom"
    assert row["session_id"] == "sess"


async def test_list_jobs_filters(store: JobStore) -> None:
    for i, user in enumerate(["alice", "bob", "alice"]):
        await store.insert_job(
            job_id=f"j{i}",
            project="p",
            agent="c",
            prompt="x",
            user_name=user,
            channel="",
            started_at=datetime.now(timezone.utc),
            status="running",
        )
    mine = await store.list_jobs(user_name="alice", limit=50)
    assert len(mine) == 2
    all_rows = await store.list_jobs(limit=50)
    assert len(all_rows) == 3


async def test_list_jobs_status_filter(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1", project="p", agent="c", prompt="x",
        user_name="", channel="",
        started_at=datetime.now(timezone.utc), status="running",
    )
    await store.insert_job(
        job_id="j2", project="p", agent="c", prompt="x",
        user_name="", channel="",
        started_at=datetime.now(timezone.utc), status="completed",
    )
    running = await store.list_jobs(status="running", limit=50)
    assert [r["id"] for r in running] == ["j1"]


async def test_insert_phases_and_update(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1",
        project="p",
        agent="c",
        prompt="x",
        user_name="",
        channel="",
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    await store.insert_phases(
        "j1",
        [
            {"step": 1, "title": "load"},
            {"step": 2, "title": "run"},
        ],
    )
    phases = await store.list_phases("j1")
    assert [p["step"] for p in phases] == [1, 2]
    assert [p["title"] for p in phases] == ["load", "run"]
    assert all(p["status"] == "pending" for p in phases)

    await store.update_phase(
        job_id="j1",
        step=1,
        status="completed",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        duration_seconds=1.5,
        output_summary="ok",
        files_changed=["a.py", "b.py"],
    )
    phases = await store.list_phases("j1")
    assert phases[0]["status"] == "completed"
    assert phases[0]["files_changed"] == ["a.py", "b.py"]
    assert phases[0]["output_summary"] == "ok"
    assert phases[0]["duration_seconds"] == 1.5


async def test_insert_phases_is_idempotent(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1", project="p", agent="c", prompt="x",
        user_name="", channel="",
        started_at=datetime.now(timezone.utc), status="running",
    )
    payload = [{"step": 1, "title": "load"}]
    await store.insert_phases("j1", payload)
    await store.insert_phases("j1", payload)  # ON CONFLICT DO NOTHING
    phases = await store.list_phases("j1")
    assert len(phases) == 1


async def test_insert_phases_empty_is_noop(store: JobStore) -> None:
    await store.insert_job(
        job_id="j1", project="p", agent="c", prompt="x",
        user_name="", channel="",
        started_at=datetime.now(timezone.utc), status="running",
    )
    await store.insert_phases("j1", [])
    assert await store.list_phases("j1") == []
