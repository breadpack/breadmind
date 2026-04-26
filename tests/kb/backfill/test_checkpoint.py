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
    # T9-review I2: asyncpg returns JSONB as raw JSON text by default (no
    # codec is registered in storage.database.Database). Pin this down so
    # future codec drift surfaces here, not in production.
    assert isinstance(row["progress_json"], str), (
        "asyncpg behavior changed — JSONB now returns dict; "
        "verify production callers"
    )
    assert json.loads(row["progress_json"]) == {"discovered": 50}
    assert json.loads(row["skipped_json"]) == {"signal_filter_short": 3}


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
    """End-to-end: runner+checkpointer writes a 'completed' row with last_cursor.

    Also proves the 50-item cadence fired mid-run (not just the finally-block
    flush). With 120 items and ``checkpoint_every_n=50`` we expect cadence
    fires at discovered=50 and discovered=100 in addition to the final flush.
    """
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

    # T9-review M3: spy on every checkpoint() call so we can assert that the
    # 50-item cadence fired *during* the loop, not only via the finally-block
    # flush. Wraps the bound method so the underlying DB write still happens.
    calls: list[dict] = []
    original_checkpoint = cp.checkpoint

    async def counting_checkpoint(**kw):
        calls.append(
            {
                "cursor": kw["cursor"],
                "discovered": kw["progress"].get("discovered"),
            }
        )
        await original_checkpoint(**kw)

    cp.checkpoint = counting_checkpoint  # type: ignore[method-assign]

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

    # Cadence assertion: at least 2 mid-run fires at discovered=50, 100.
    mid_run = [c for c in calls if c["discovered"] in (50, 100)]
    assert len(mid_run) >= 2, f"expected mid-run cadence fires, got {calls}"


async def test_runner_finishes_row_when_teardown_raises(
    test_db, insert_org, fake_redactor, fake_embedder,
):
    """Even if teardown() raises, the kb_backfill_jobs row must converge to terminal status.

    T9-review I1: connector cleanup blip must not leave the row stuck at
    status='running' forever; the original teardown error still propagates.
    """
    import pytest as _pt

    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill.runner import BackfillRunner
    from tests.kb.backfill.test_runner import _StubJob, _item

    class _ExplodingTeardownJob(_StubJob):
        async def teardown(self) -> None:
            raise RuntimeError("teardown boom")

    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(3)]
    job = _ExplodingTeardownJob(
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
    with _pt.raises(RuntimeError, match="teardown boom"):
        await runner.run(job)
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, finished_at, error FROM kb_backfill_jobs "
            "WHERE org_id=$1 ORDER BY created_at DESC LIMIT 1",
            org_id,
        )
    assert row["status"] == "failed"
    assert row["finished_at"] is not None
    assert "teardown failed" in (row["error"] or "")
