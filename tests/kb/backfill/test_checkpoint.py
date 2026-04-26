"""Tests for JobCheckpointer — kb_backfill_jobs row lifecycle (Task 9)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from breadmind.kb.backfill.checkpoint import (
    JobCheckpointer,
    load_resume_cursor,
)


async def test_checkpointer_creates_pending_row(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={"channels": ["C1"]},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=500_000,
        created_by="alice",
    )
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, instance_id FROM kb_backfill_jobs WHERE id=$1",
            job_id,
        )
    assert row["status"] == "running"
    assert row["instance_id"] == "T1"


async def test_checkpoint_writes_cursor_and_progress(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10,
        created_by="t",
    )
    await cp.checkpoint(
        job_id=job_id,
        cursor="1730000000:C1:1.0",
        progress={"discovered": 50},
        skipped={"signal_filter_short": 3},
    )
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_cursor, progress_json, skipped_json "
            "FROM kb_backfill_jobs WHERE id=$1",
            job_id,
        )
    assert row["last_cursor"] == "1730000000:C1:1.0"
    # asyncpg may return JSONB as str or dict depending on codec setup.
    progress_data = (
        json.loads(row["progress_json"])
        if isinstance(row["progress_json"], str)
        else row["progress_json"]
    )
    skipped_data = (
        json.loads(row["skipped_json"])
        if isinstance(row["skipped_json"], str)
        else row["skipped_json"]
    )
    assert progress_data == {"discovered": 50}
    assert skipped_data == {"signal_filter_short": 3}


async def test_load_resume_cursor_returns_last_cursor(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10,
        created_by="t",
    )
    await cp.checkpoint(job_id=job_id, cursor="X", progress={}, skipped={})
    assert await load_resume_cursor(test_db, job_id) == "X"


async def test_finish_sets_status_and_finished_at(test_db, insert_org):
    """Cover finish() — completed status path."""
    org_id = uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10,
        created_by="t",
    )
    await cp.finish(job_id=job_id, status="completed")
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, finished_at, error FROM kb_backfill_jobs WHERE id=$1",
            job_id,
        )
    assert row["status"] == "completed"
    assert row["finished_at"] is not None
    assert row["error"] is None


async def test_runner_writes_checkpoint_on_completion(
    test_db, insert_org, fake_redactor, fake_embedder,
):
    """End-to-end: runner+checkpointer writes a 'completed' row with last_cursor."""
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill.runner import BackfillRunner
    from tests.kb.backfill.test_runner import _StubJob, _item

    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(120)]
    job = _StubJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
    )
    cp = JobCheckpointer(db=test_db)
    runner = BackfillRunner(
        db=test_db,
        redactor=fake_redactor,
        embedder=fake_embedder,
        checkpointer=cp,
        checkpoint_every_n=50,
    )
    await runner.run(job)
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, last_cursor FROM kb_backfill_jobs "
            "WHERE org_id=$1 ORDER BY created_at DESC LIMIT 1",
            org_id,
        )
    assert row["status"] == "completed"
    assert row["last_cursor"] is not None  # x119 (or last item processed)
