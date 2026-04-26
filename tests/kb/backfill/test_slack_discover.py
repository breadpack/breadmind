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
