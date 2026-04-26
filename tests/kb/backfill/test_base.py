from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.base import (
    BackfillItem,
    BackfillJob,
    JobProgress,
    JobReport,
    Skipped,
)


def _ts() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_backfill_item_required_fields():
    item = BackfillItem(
        source_kind="slack_msg",
        source_native_id="C1:1.0",
        source_uri="https://slack/p1",
        source_created_at=_ts(),
        source_updated_at=_ts(),
        title="t",
        body="b",
        author="U1",
    )
    assert item.parent_ref is None
    assert item.extra == {}


def test_backfill_item_is_frozen():
    item = BackfillItem(
        source_kind="slack_msg",
        source_native_id="x",
        source_uri="u",
        source_created_at=_ts(),
        source_updated_at=_ts(),
        title="t",
        body="b",
        author=None,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        item.body = "z"  # type: ignore[misc]


def test_backfill_item_parent_ref_format():
    item = BackfillItem(
        source_kind="slack_msg",
        source_native_id="C1:1.1",
        source_uri="u",
        source_created_at=_ts(),
        source_updated_at=_ts(),
        title="t",
        body="b",
        author=None,
        parent_ref="slack_msg:C1:1.0",
    )
    assert item.parent_ref.startswith("slack_msg:")


def test_backfill_item_dual_timestamps_independent():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updated = datetime(2026, 4, 1, tzinfo=timezone.utc)
    item = BackfillItem(
        source_kind="slack_msg",
        source_native_id="x",
        source_uri="u",
        source_created_at=created,
        source_updated_at=updated,
        title="t",
        body="b",
        author=None,
    )
    assert item.source_created_at != item.source_updated_at


def test_job_progress_defaults_zero():
    p = JobProgress()
    assert p.discovered == 0 and p.embedded == 0 and p.tokens_consumed == 0
    assert p.last_cursor is None


def test_job_progress_mutable():
    p = JobProgress()
    p.discovered += 1
    p.last_cursor = "abc"
    assert p.discovered == 1 and p.last_cursor == "abc"


def test_job_report_skipped_is_dict():
    r = JobReport(
        job_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        source_kind="slack_msg",
        dry_run=True,
        estimated_count=0,
        estimated_tokens=0,
        indexed_count=0,
    )
    assert r.skipped == {}
    assert r.sample_titles == [] and r.budget_hit is False
    assert r.cursor is None


def test_job_report_cursor_is_opaque_str():
    r = JobReport(
        job_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        source_kind="slack_msg",
        dry_run=False,
        estimated_count=10,
        estimated_tokens=100,
        indexed_count=10,
        cursor="1730000000:C1:1.0",
    )
    # Pipeline never parses; just stores verbatim.
    assert isinstance(r.cursor, str)


class _Concrete(BackfillJob):
    source_kind = "slack_msg"

    async def prepare(self) -> None: ...

    async def discover(self) -> AsyncIterator[BackfillItem]:
        if False:
            yield  # type: ignore[unreachable]

    def filter(self, item: BackfillItem) -> bool:
        return True

    def instance_id_of(self, source_filter: dict) -> str:
        return "T1"


def test_backfill_job_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        BackfillJob(  # type: ignore[abstract]
            org_id=uuid.uuid4(),
            source_filter={},
            since=datetime.now(timezone.utc),
            until=datetime.now(timezone.utc),
            dry_run=True,
            token_budget=1,
        )


def test_backfill_job_concrete_constructs():
    job = _Concrete(
        org_id=uuid.uuid4(),
        source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=500_000,
    )
    assert job.source_kind == "slack_msg"
    assert job.instance_id_of({}) == "T1"


def test_cursor_of_default_returns_native_id():
    job = _Concrete(
        org_id=uuid.uuid4(),
        source_filter={},
        since=datetime.now(timezone.utc),
        until=datetime.now(timezone.utc),
        dry_run=True,
        token_budget=1,
    )
    item = BackfillItem(
        source_kind="slack_msg",
        source_native_id="X1",
        source_uri="u",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
        title="t",
        body="b",
        author=None,
    )
    assert job.cursor_of(item) == "X1"


def test_skipped_exception_carries_reason():
    e = Skipped("acl_lock")
    assert e.reason == "acl_lock"
