from __future__ import annotations

from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.base import BackfillItem


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
