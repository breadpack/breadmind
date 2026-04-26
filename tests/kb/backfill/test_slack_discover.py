from __future__ import annotations
import uuid
from datetime import datetime, timezone
import pytest
from breadmind.kb.backfill.slack import SlackBackfillAdapter

pytestmark = pytest.mark.asyncio


class FakeSlackSession:
    def __init__(self, payloads: dict[str, list[dict]]):
        self._payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, **params):
        self.calls.append((method, params))
        return self._payloads[method].pop(0)


class FakeVault:
    async def retrieve(self, ref: str) -> str | None:
        return "xoxb-token"


async def test_prepare_snapshots_membership_and_team_id():
    session = FakeSlackSession({
        "auth.test": [{"ok": True, "team_id": "T123"}],
        "conversations.info": [
            {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
        "conversations.members": [
            {"ok": True, "members": ["U1", "U2"], "response_metadata": {}}],
    })
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=1, vault=FakeVault(),
        credentials_ref="slack:org", session=session)
    await job.prepare()
    assert job._membership_snapshot == frozenset({"U1", "U2"})
    assert job._team_id == "T123"


async def test_prepare_fail_closed_on_archived_channel():
    session = FakeSlackSession({
        "auth.test": [{"ok": True, "team_id": "T1"}],
        "conversations.info": [
            {"ok": True, "channel": {"id": "C1", "is_archived": True}}],
    })
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False, token_budget=1, vault=FakeVault(),
        credentials_ref="slack:org", session=session)
    with pytest.raises(PermissionError, match="archived"):
        await job.prepare()


def test_instance_id_of_returns_team_id():
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=1, vault=FakeVault(),
        credentials_ref="slack:org", session=None)
    job._team_id = "T999"
    assert job.instance_id_of(job.source_filter) == "T999"


async def test_discover_yields_top_level_messages_in_window():
    session = FakeSlackSession({
        "auth.test": [{"ok": True, "team_id": "T1"}],
        "conversations.info": [
            {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
        "conversations.members": [
            {"ok": True, "members": ["U1"], "response_metadata": {}}],
        "conversations.history": [
            {"ok": True, "messages": [
                {"ts": "1735689600.0", "user": "U1",
                 "text": "hello", "permalink": "https://x"},
                {"ts": "1735776000.0", "user": "U1",
                 "text": "world", "permalink": "https://y"},
            ], "has_more": False}],
    })
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=10**9, vault=FakeVault(),
        credentials_ref="slack:o", session=session)
    await job.prepare()
    out = [it async for it in job.discover()]
    assert len(out) == 2
    assert out[0].source_native_id == "C1:1735689600.0"


async def test_discover_threads_collapse_to_one_item():
    replies_payload = {"ok": True, "messages": [
        {"ts": "1.0", "thread_ts": "1.0", "text": "Q?", "user": "U1"},
        {"ts": "1.1", "thread_ts": "1.0", "text": "A.", "user": "U2"},
    ], "has_more": False}
    session = FakeSlackSession({
        "auth.test": [{"ok": True, "team_id": "T1"}],
        "conversations.info": [
            {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
        "conversations.members": [
            {"ok": True, "members": ["U1", "U2"], "response_metadata": {}}],
        "conversations.history": [{"ok": True, "messages": [
            {"ts": "1.0", "thread_ts": "1.0", "reply_count": 1,
             "user": "U1", "text": "Q?"}], "has_more": False}],
        "conversations.replies": [replies_payload],
    })
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={
            "channels": ["C1"], "include_threads": True},
        since=datetime(1970, 1, 1, tzinfo=timezone.utc),
        until=datetime(2099, 1, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=10**9, vault=FakeVault(),
        credentials_ref="slack:o", session=session)
    await job.prepare()
    out = [it async for it in job.discover()]
    assert len(out) == 1
    assert out[0].source_native_id == "C1:1.0:thread"
    assert "Q?" in out[0].body and "A." in out[0].body


async def test_discover_retries_on_429_with_retry_after():
    session = FakeSlackSession({
        "auth.test": [{"ok": True, "team_id": "T1"}],
        "conversations.info": [
            {"ok": True, "channel": {"id": "C1", "is_archived": False}}],
        "conversations.members": [
            {"ok": True, "members": [], "response_metadata": {}}],
        "conversations.history": [
            {"ok": False, "error": "ratelimited",
             "_status": 429, "_retry_after": 0},  # interpreted as 0s sleep
            {"ok": True, "messages": [], "has_more": False}],
    })
    job = SlackBackfillAdapter(
        org_id=uuid.uuid4(), source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=True, token_budget=1, vault=FakeVault(),
        credentials_ref="slack:o", session=session)
    await job.prepare()
    _ = [it async for it in job.discover()]
    methods = [c[0] for c in session.calls]
    assert methods.count("conversations.history") == 2
