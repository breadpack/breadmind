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
