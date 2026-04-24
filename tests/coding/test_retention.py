"""Tests for ``JobStore.delete_old_jobs`` — retention cron target.

The Task 23 retention cron prunes completed jobs whose ``finished_at`` is
older than ``BREADMIND_JOBS_RETENTION_DAYS`` (default 90). This module
exercises the delete helper directly against the migrated test DB.

The ``delete_old_jobs`` implementation lives in Task 3 and this test
pins its contract so future changes to the retention query don't
silently change which rows are kept.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from breadmind.coding.job_store import JobStore


@pytest.fixture
def store(test_db) -> JobStore:
    return JobStore(test_db)


@pytest.fixture(autouse=True)
async def _isolate_coding_tables(test_db):
    """Ensure each test starts with an empty coding_jobs table."""
    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM coding_jobs")
    yield


async def test_delete_old_jobs(store: JobStore) -> None:
    """Rows finished before the cutoff are removed; fresh rows survive."""
    old = datetime.now(timezone.utc) - timedelta(days=100)
    recent = datetime.now(timezone.utc) - timedelta(days=10)

    await store.insert_job(
        job_id="old",
        project="p",
        agent="c",
        prompt="",
        user_name="",
        channel="",
        started_at=old,
        status="completed",
    )
    await store.update_job(job_id="old", status="completed", finished_at=old)

    await store.insert_job(
        job_id="new",
        project="p",
        agent="c",
        prompt="",
        user_name="",
        channel="",
        started_at=recent,
        status="completed",
    )
    await store.update_job(
        job_id="new", status="completed", finished_at=recent
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    n = await store.delete_old_jobs(finished_before=cutoff)

    assert n == 1
    assert await store.get_job("old") is None
    assert await store.get_job("new") is not None


async def test_delete_old_jobs_skips_running(store: JobStore) -> None:
    """Jobs still running (``finished_at IS NULL``) must never be deleted."""
    very_old = datetime.now(timezone.utc) - timedelta(days=365)

    await store.insert_job(
        job_id="still-running",
        project="p",
        agent="c",
        prompt="",
        user_name="",
        channel="",
        started_at=very_old,
        status="running",
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    n = await store.delete_old_jobs(finished_before=cutoff)

    assert n == 0
    assert await store.get_job("still-running") is not None
