"""Integration scenarios A / B / C / pin for the episodic loop.

These tests exercise the full recorder + store pipeline against a real
PostgreSQL via the shared ``test_db`` fixture (see ``tests/conftest.py``).

The shared fixture is non-isolated across tests (carry-over #3 in the
Phase 1 plan), so each scenario uses a unique ``user_id`` to avoid
cross-test contamination.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
from breadmind.memory.episodic_store import EpisodicFilter, PostgresEpisodicStore
from breadmind.memory.event_types import SignalKind, stable_hash
from breadmind.memory.signals import SignalDetector, TurnSnapshot


def _uid(tag: str) -> str:
    """Unique per-test user_id to keep the non-isolated fixture clean."""
    return f"alice-{tag}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_scenario_A_dialog_continuity(test_db):
    """Tool runs in session 1; in session 2 the recall pulls the prior fact."""
    user_id = _uid("A")
    store = PostgresEpisodicStore(test_db)
    llm = AsyncMock()
    llm.complete_json.return_value = {
        "summary": "VPC ap-northeast-2 was created.",
        "keywords": ["vpc", "ap-northeast-2"],
        "outcome": "success",
        "should_record": True,
    }
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=True))
    sig = SignalDetector()

    sid1 = uuid.uuid4()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=sid1,
        user_message="VPC를 ap-northeast-2에 만들어줘",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-2"},
        ok=True,
        result_text="vpc-001 created",
    )
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query="어제 그 VPC 어떻게 됐지?",
        filters=EpisodicFilter(),
        limit=5,
    )
    assert any(
        "ap-northeast-2" in (n.summary + " ".join(n.keywords)) for n in notes
    )


@pytest.mark.asyncio
async def test_scenario_B_task_recall_same_args(test_db):
    """Same tool with same args -> digest match should boost recall to top."""
    user_id = _uid("B")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=uuid.uuid4(),
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )

    args = {"region": "ap-northeast-2", "name": "vpc-a"}
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args=args,
        ok=True,
        result_text="vpc-001 created",
    )
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="aws_vpc_create",
            tool_args_digest=stable_hash(args),
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
        ),
        limit=3,
    )
    assert notes and notes[0].tool_args_digest == stable_hash(args)


@pytest.mark.asyncio
async def test_scenario_C_failure_learning(test_db):
    """A failure on tool X should surface first when X is invoked again."""
    user_id = _uid("C")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=None,
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    e1 = sig.on_tool_finished(
        snap, tool_name="t", tool_args={"a": 1}, ok=True, result_text="ok"
    )
    await rec.record(e1)
    e2 = sig.on_tool_finished(
        snap, tool_name="t", tool_args={"a": 2}, ok=False, result_text="boom"
    )
    await rec.record(e2)

    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="t",
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
        ),
        limit=3,
    )
    assert notes[0].outcome == "failure"


@pytest.mark.asyncio
async def test_scenario_pin(test_db):
    """An explicit pin should be persisted and surfaced first on later recall."""
    user_id = _uid("pin")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=None,
        user_message="기억해줘: API key는 vault X에 있다",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    evt = sig.on_user_message(snap)
    assert evt and evt.kind is SignalKind.EXPLICIT_PIN
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query="API key 어디에 있지?",
        filters=EpisodicFilter(),
        limit=5,
    )
    assert any(n.pinned for n in notes)


# ── T9: Multi-tenancy integration scenarios 5/6/7/8 ─────────────────────────


@pytest.mark.asyncio
async def test_scenario_5_two_tenant_isolation(test_db, insert_org):
    """Two distinct orgs, same user_id → recall is isolated per-org filter.

    Records two notes through the SignalDetector → EpisodicRecorder → store
    pipeline, stamping each ``TurnSnapshot`` with a different ``org_id``.
    Verifies the org_id propagates from snapshot → event → note → SQL.
    """
    user_id = _uid("5")
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    await insert_org(org_a)
    await insert_org(org_b)

    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()

    # Distinguishing keyword so we can fish only this scenario's notes out.
    kw = f"twoTenant{uuid.uuid4().hex[:6]}"

    async def _record(org_id: uuid.UUID, vpc_name: str) -> None:
        snap = TurnSnapshot(
            user_id=user_id,
            session_id=uuid.uuid4(),
            user_message="",
            last_tool_name=None,
            prior_turn_summary=None,
            org_id=org_id,
        )
        evt = sig.on_tool_finished(
            snap,
            tool_name="aws_vpc_create",
            tool_args={"region": "ap-northeast-2", "name": vpc_name, "tag": kw},
            ok=True,
            result_text=f"vpc {vpc_name} created",
        )
        # Sanity-check that the recorder will see the org_id via the event.
        assert evt.org_id == org_id
        await rec.record(evt)

    await _record(org_a, "vpc-a")
    await _record(org_b, "vpc-b")

    # The raw_note path falls back to keyword_extract on content, so query by
    # tool_name + same digest. tool_args differ between A and B (vpc_name), so
    # we filter by user_id + tool_name + org_id and rely on the org_id clause.
    common_filter_kwargs = dict(
        tool_name="aws_vpc_create",
        kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
    )

    res_a = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(org_id=org_a, **common_filter_kwargs),
        limit=10,
    )
    contents_a = [n.content for n in res_a]
    assert any("vpc-a" in c for c in contents_a), (
        f"org_a filter must surface vpc-a note; got {contents_a!r}"
    )
    assert not any("vpc-b" in c for c in contents_a), (
        f"org_a filter must NOT surface vpc-b note; got {contents_a!r}"
    )

    res_b = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(org_id=org_b, **common_filter_kwargs),
        limit=10,
    )
    contents_b = [n.content for n in res_b]
    assert any("vpc-b" in c for c in contents_b), (
        f"org_b filter must surface vpc-b note; got {contents_b!r}"
    )
    assert not any("vpc-a" in c for c in contents_b), (
        f"org_b filter must NOT surface vpc-a note; got {contents_b!r}"
    )

    # org_id=None → no org clause → both notes returned.
    res_all = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(org_id=None, **common_filter_kwargs),
        limit=10,
    )
    contents_all = [n.content for n in res_all]
    assert any("vpc-a" in c for c in contents_all)
    assert any("vpc-b" in c for c in contents_all)


@pytest.mark.asyncio
async def test_scenario_6_single_tenant_fallback(test_db, monkeypatch):
    """env / explicit / ctx all None → Phase 1 single-tenant behaviour intact.

    Confirms the new org_id machinery has zero observable effect when nothing
    is wired: snapshot.org_id=None → event.org_id=None → note.org_id IS NULL,
    and an org_id=None search returns the note.
    """
    monkeypatch.delenv("BREADMIND_DEFAULT_ORG_ID", raising=False)
    user_id = _uid("6")

    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()

    snap = TurnSnapshot(
        user_id=user_id,
        session_id=uuid.uuid4(),
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
        org_id=None,  # explicit single-tenant
    )
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-1"},
        ok=True,
        result_text="vpc-single created",
    )
    assert evt.org_id is None
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="aws_vpc_create",
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
            org_id=None,
        ),
        limit=5,
    )
    assert notes, "single-tenant recall must return the recorded note"
    assert all(n.org_id is None for n in notes if n.user_id == user_id), (
        "single-tenant note must persist with org_id=NULL"
    )


@pytest.mark.asyncio
async def test_scenario_7_fk_set_null_on_org_delete(test_db, insert_org):
    """Deleting an org_projects row must SET NULL the FK on episodic_notes.

    Migration 009 declares ``ON DELETE SET NULL`` on episodic_notes.org_id;
    this round-trips the constraint against a real DB.
    """
    user_id = _uid("7")
    org_a = uuid.uuid4()
    await insert_org(org_a)

    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=uuid.uuid4(),
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
        org_id=org_a,
    )
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args={"region": "us-east-1", "name": "vpc-fk"},
        ok=True,
        result_text="vpc-fk created",
    )
    await rec.record(evt)

    # Locate the freshly persisted note id via the recorder's pipeline output.
    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="aws_vpc_create",
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
            org_id=org_a,
        ),
        limit=5,
    )
    assert notes, "note must be persisted before FK test"
    note_id = notes[0].id
    assert note_id is not None
    assert notes[0].org_id == org_a

    # Delete the org row → FK SET NULL should cascade onto episodic_notes.org_id.
    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM org_projects WHERE id = $1", org_a)
        row = await conn.fetchrow(
            "SELECT org_id FROM episodic_notes WHERE id = $1", note_id
        )
    assert row is not None, "episodic_notes row must still exist after org delete"
    assert row["org_id"] is None, (
        f"FK ON DELETE SET NULL must null out org_id; got {row['org_id']!r}"
    )


@pytest.mark.asyncio
async def test_scenario_8_slack_lookup_roundtrip(test_db, insert_org):
    """Real-DB roundtrip for the Slack team_id → org_id lookup helper.

    Unit tests in ``tests/memory/test_org_id_resolver.py`` already cover
    cache/warn semantics via mocked DBs; this scenario confirms the SQL
    resolves against an actual ``org_projects`` row inserted via the shared
    fixture.
    """
    from breadmind.memory.runtime import (
        _lookup_org_id_by_slack_team,
        clear_org_lookup_cache,
    )

    org_a = uuid.uuid4()
    await insert_org(org_a)
    # ``insert_org`` writes ``slack_team_id = "T" + str(org_id)[:8]``.
    team_id = f"T{str(org_a)[:8]}"

    clear_org_lookup_cache()
    try:
        first = await _lookup_org_id_by_slack_team(team_id, test_db)
        assert first == org_a

        # Cached value must match (cache-hit semantics covered by unit tests).
        second = await _lookup_org_id_by_slack_team(team_id, test_db)
        assert second == org_a

        # Unknown team_id → None (and cache the miss).
        unknown = await _lookup_org_id_by_slack_team("T99999999", test_db)
        assert unknown is None
    finally:
        clear_org_lookup_cache()
