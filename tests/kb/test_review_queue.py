"""Tests for ReviewQueue.enqueue (Task 6)."""
from __future__ import annotations

from breadmind.kb.review_queue import ReviewQueue
from breadmind.kb.types import ExtractedCandidate


def _candidate(pid, *, title="t", category="howto", conf=0.9, sensitive=False):
    return ExtractedCandidate(
        proposed_title=title,
        proposed_body="body",
        proposed_category=category if not sensitive else "sensitive_blocked",
        confidence=conf,
        sources=[],
        original_user="U-AUTHOR",
        project_id=pid,
        sensitive_flag=sensitive,
    )


async def test_enqueue_inserts_pending_row(db, seeded_project, fake_slack_client):
    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_candidate(seeded_project))
    assert cid > 0
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, sensitive_flag, proposed_title "
            "FROM promotion_candidates WHERE id=$1",
            cid,
        )
    assert row["status"] == "pending"
    assert row["sensitive_flag"] is False
    assert row["proposed_title"] == "t"


async def test_enqueue_sensitive_sets_needs_edit(db, seeded_project, fake_slack_client):
    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_candidate(seeded_project, sensitive=True))
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, sensitive_flag FROM promotion_candidates WHERE id=$1",
            cid,
        )
    assert row["status"] == "needs_edit"
    assert row["sensitive_flag"] is True


async def test_enqueue_writes_audit(db, seeded_project, fake_slack_client):
    rq = ReviewQueue(db, fake_slack_client)
    await rq.enqueue(_candidate(seeded_project))
    async with db.acquire() as conn:
        actions = [
            r["action"]
            for r in await conn.fetch(
                "SELECT action FROM kb_audit_log WHERE project_id=$1", seeded_project
            )
        ]
    assert "enqueue_candidate" in actions


async def test_list_pending_returns_pending_only(db, seeded_project, fake_slack_client):
    rq = ReviewQueue(db, fake_slack_client)
    await rq.enqueue(_candidate(seeded_project, title="p1"))
    p2 = await rq.enqueue(_candidate(seeded_project, title="p2"))
    # Mark p2 as rejected directly
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE promotion_candidates SET status='rejected' WHERE id=$1",
            p2,
        )
    out = await rq.list_pending(seeded_project)
    titles = [c.proposed_title for c in out]
    assert "p1" in titles
    assert "p2" not in titles


async def test_list_pending_limit(db, seeded_project, fake_slack_client):
    rq = ReviewQueue(db, fake_slack_client)
    for i in range(5):
        await rq.enqueue(_candidate(seeded_project, title=f"p{i}"))
    out = await rq.list_pending(seeded_project, limit=3)
    assert len(out) == 3


# ---------------------------------------------------------------------------
# Task 8 — approve()
# ---------------------------------------------------------------------------


async def test_approve_inserts_knowledge_and_copies_sources(
    db, seeded_project, fake_slack_client, monkeypatch
):
    async def fake_embed(text: str):
        return [0.1] * 384
    from breadmind.kb import review_queue as rq_mod
    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)

    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_candidate(seeded_project, title="howto-1"))
    # Inject a source so we can verify copy
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE promotion_candidates SET sources_json = $1::jsonb WHERE id=$2",
            '[{"source_type":"slack_msg","source_uri":"u","source_ref":"r"}]',
            cid,
        )
    kid = await rq.approve(cid, reviewer="U-LEAD")
    assert kid > 0

    async with db.acquire() as conn:
        knowledge = await conn.fetchrow(
            "SELECT title, category, promoted_by FROM org_knowledge WHERE id=$1",
            kid,
        )
        sources = await conn.fetch(
            "SELECT source_type, source_uri FROM kb_sources WHERE knowledge_id=$1",
            kid,
        )
        cand_status = await conn.fetchval(
            "SELECT status FROM promotion_candidates WHERE id=$1", cid
        )
    assert knowledge["title"] == "howto-1"
    assert knowledge["promoted_by"] == "U-LEAD"
    assert len(sources) == 1
    assert sources[0]["source_type"] == "slack_msg"
    assert cand_status == "approved"


async def test_approve_dms_original_user(
    db, seeded_project, fake_slack_client, monkeypatch
):
    async def fake_embed(text: str):
        return [0.1] * 384
    from breadmind.kb import review_queue as rq_mod
    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)

    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_candidate(seeded_project))
    await rq.approve(cid, reviewer="U-LEAD")
    # DM sent to U-AUTHOR via FakeSlackClient (channel = "D-U-AUTHOR")
    dm_channels = [dm.get("channel", "") for dm in fake_slack_client.dms]
    assert any("U-AUTHOR" in ch for ch in dm_channels)


async def test_approve_superseded_by_chain(
    db, seeded_project, fake_slack_client, monkeypatch
):
    # Both approvals get identical embedding → cosine similarity = 1.0 → chain
    async def fake_embed(text: str):
        return [1.0] + [0.0] * 383
    from breadmind.kb import review_queue as rq_mod
    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)

    rq = ReviewQueue(db, fake_slack_client)
    cid1 = await rq.enqueue(_candidate(seeded_project, title="first"))
    kid1 = await rq.approve(cid1, reviewer="U-LEAD")
    cid2 = await rq.enqueue(_candidate(seeded_project, title="second"))
    kid2 = await rq.approve(cid2, reviewer="U-LEAD")

    async with db.acquire() as conn:
        superseded = await conn.fetchval(
            "SELECT superseded_by FROM org_knowledge WHERE id=$1", kid1
        )
    assert superseded == kid2
