"""Tests for BackfillRunner — Task 7 (prepare + dry-run estimation)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

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
