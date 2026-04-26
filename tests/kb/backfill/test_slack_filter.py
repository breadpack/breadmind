from __future__ import annotations
import uuid
from datetime import datetime, timezone
import pytest
from breadmind.kb.backfill.base import BackfillItem
from breadmind.kb.backfill.slack import SlackBackfillAdapter


def _job():
    class _NullVault:
        async def retrieve(self, *_): return None
    j = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=1, vault=_NullVault(),
        credentials_ref="x", session=None)
    j._membership_snapshot = frozenset({"U1", "U2"})
    return j


def _it(body: str, **extra) -> BackfillItem:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BackfillItem(
        source_kind="slack_msg", source_native_id="C1:1.0",
        source_uri="u", source_created_at=ts, source_updated_at=ts,
        title="t", body=body, author=extra.pop("author", "U1"),
        extra={"subtype": None, "reaction_count": 1, "reply_count": 0,
               **extra})


def test_filter_drops_short_message():
    j = _job()
    it = _it("hi")
    assert j.filter(it) is False
    assert it.extra["_skip_reason"] == "signal_filter_short"


def test_filter_drops_bot_subtype():
    j = _job()
    it = _it("a long enough body", subtype="bot_message")
    assert j.filter(it) is False
    assert it.extra["_skip_reason"] == "signal_filter_bot"


def test_filter_drops_zero_engagement_no_thread():
    j = _job()
    it = _it("a long enough body", reaction_count=0, reply_count=0)
    assert j.filter(it) is False
    assert it.extra["_skip_reason"] == "signal_filter_no_engagement"


def test_filter_drops_pure_mention_only():
    j = _job()
    it = _it("<@U99> <#C00>")
    assert j.filter(it) is False
    assert it.extra["_skip_reason"] == "signal_filter_mention_only"


def test_filter_keeps_engaged_long_message():
    j = _job()
    it = _it("real recap of postgres tuning", reaction_count=2)
    assert j.filter(it) is True


def test_filter_acl_lock_label():
    j = _job()
    it = _it("real content here", reaction_count=2, author="U_ALIEN")
    assert j.filter(it) is False
    assert it.extra["_skip_reason"] == "acl_lock"


def test_filter_thresholds_tunable():
    j = _job()
    j.config = {"min_length": 20, "drop_zero_engagement": False}
    it = _it("short but long enough?")  # 22 chars; reaction=0, reply=0
    assert j.filter(it) is True


def test_cursor_of_top_level_format():
    j = _job()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = BackfillItem(
        source_kind="slack_msg", source_native_id="C1:1735689600.0",
        source_uri="u", source_created_at=ts, source_updated_at=ts,
        title="t", body="b", author="U1")
    cur = j.cursor_of(item)
    # f"{ts_ms}:{channel_id}:{message_ts}"
    assert cur == f"{int(ts.timestamp() * 1000)}:C1:1735689600.0"


def test_cursor_of_thread_format():
    j = _job()
    ts = datetime(2026, 2, 15, tzinfo=timezone.utc)
    item = BackfillItem(
        source_kind="slack_msg", source_native_id="C1:1.0:thread",
        source_uri="u", source_created_at=ts, source_updated_at=ts,
        title="t", body="b", author="U1")
    cur = j.cursor_of(item)
    assert cur.endswith(":C1:1.0:thread") or cur.endswith(":C1:1.0")
