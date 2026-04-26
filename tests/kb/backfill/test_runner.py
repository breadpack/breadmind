"""Tests for BackfillRunner — Task 7 (prepare + dry-run estimation) + Task 8 (real-run)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.base import BackfillItem, BackfillJob
from breadmind.kb.backfill.runner import BackfillRunner


class _StubJob(BackfillJob):
    source_kind = "slack_msg"

    def __init__(self, items, **kw):
        super().__init__(**kw)
        self._items = items
        self.prepared = False

    async def prepare(self) -> None:
        self.prepared = True

    async def discover(self) -> AsyncIterator[BackfillItem]:
        for it in self._items:
            yield it

    def filter(self, item: BackfillItem) -> bool:
        return True

    def instance_id_of(self, source_filter):
        return "T1"


def _item(i: int) -> BackfillItem:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BackfillItem(
        source_kind="slack_msg",
        source_native_id=f"x{i}",
        source_uri="u",
        source_created_at=ts,
        source_updated_at=ts,
        title=f"t{i}",
        body="hello world",
        author="U1",
    )


async def test_runner_calls_prepare_before_discover(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    job = _StubJob(
        [_item(0)],
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=10_000,
    )
    runner = BackfillRunner(db=test_db, redactor=None, embedder=None)
    await runner.run(job)
    assert job.prepared is True


async def test_dry_run_skips_redact_embed_store(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(3)]
    job = _StubJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=10_000,
    )
    runner = BackfillRunner(db=test_db, redactor=None, embedder=None)
    report = await runner.run(job)
    assert report.dry_run is True
    assert report.estimated_count == 3
    # Body "hello world" is 11 chars; 11 // 4 == 2 tokens per item; 3 items = 6.
    assert report.estimated_tokens == sum(len("hello world") // 4 for _ in items)
    assert report.indexed_count == 0
    assert len(report.sample_titles) == 3


# ---------------------------------------------------------------------------
# Task 8 — real-run pipeline tests
# ---------------------------------------------------------------------------


async def test_runner_full_pipeline_inserts_org_knowledge(
    test_db, insert_org, fake_redactor, fake_embedder
):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(3)]
    job = _StubJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10_000,
    )
    runner = BackfillRunner(
        db=test_db, redactor=fake_redactor, embedder=fake_embedder
    )
    report = await runner.run(job)
    assert report.dry_run is False
    assert report.indexed_count == 3
    assert report.errors == 0
    assert report.budget_hit is False
    rows = await test_db.fetch(
        "SELECT source_native_id FROM org_knowledge "
        "WHERE project_id=$1 AND source_kind='slack_msg' "
        "ORDER BY source_native_id",
        org_id,
    )
    assert [r["source_native_id"] for r in rows] == ["x0", "x1", "x2"]


async def test_runner_token_budget_halts_midway(
    test_db, insert_org, fake_redactor, fake_embedder
):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    # Body "hello world" is 11 chars => 11 // 4 == 2 tokens per item.
    items = [_item(i) for i in range(20)]
    job = _StubJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=4,
    )
    runner = BackfillRunner(
        db=test_db, redactor=fake_redactor, embedder=fake_embedder
    )
    report = await runner.run(job)
    assert report.budget_hit is True
    assert report.indexed_count < 20
    assert report.skipped.get("budget_halted", 0) >= 1


async def test_runner_aborts_on_10pct_error_rate(
    test_db, insert_org, fake_redactor, exploding_embedder
):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(250)]
    job = _StubJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10_000,
    )
    runner = BackfillRunner(
        db=test_db, redactor=fake_redactor, embedder=exploding_embedder
    )
    with pytest.raises(RuntimeError, match="error rate"):
        await runner.run(job)


# ---------------------------------------------------------------------------
# T7 follow-up M7: filter-returns-False accumulates skipped + estimated_count
# reflects rejections.
# ---------------------------------------------------------------------------


class _AlternatingFilterJob(_StubJob):
    """Stub job whose ``filter()`` returns False for every other item."""

    def filter(self, item: BackfillItem) -> bool:
        # Item ids look like "x0", "x1", ... — drop odd indices.
        idx = int(item.source_native_id.lstrip("x"))
        return idx % 2 == 0


async def test_runner_filter_false_accumulates_skipped(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    items = [_item(i) for i in range(6)]
    job = _AlternatingFilterJob(
        items,
        org_id=org_id,
        source_filter={},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=10_000,
    )
    runner = BackfillRunner(db=test_db, redactor=None, embedder=None)
    report = await runner.run(job)
    assert report.skipped.get("filtered", 0) == 3
    # Dry-run estimated_count = discovered (6) - filtered_out (3) = 3.
    assert report.estimated_count == 3
