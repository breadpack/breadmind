"""Tests for the feedback loop (Task 15)."""
from __future__ import annotations

from breadmind.kb.feedback import (
    _RE_REVIEW_FLAG_THRESHOLD,
    FeedbackHandler,
    build_feedback_blocks,
)


def test_build_feedback_blocks_has_three_buttons():
    blocks = build_feedback_blocks(knowledge_id=10, query_id="q-1")
    action_block = next(b for b in blocks if b["type"] == "actions")
    ids = [e["action_id"] for e in action_block["elements"]]
    assert "kb_fb_up:10:q-1" in ids
    assert "kb_fb_down:10:q-1" in ids
    assert "kb_fb_bookmark:10:q-1" in ids


async def _insert_knowledge(db, project_id) -> int:
    async with db.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO org_knowledge (project_id, title, body, category)
            VALUES ($1, 't', 'b', 'howto') RETURNING id
            """,
            project_id,
        )


async def test_upvote_increments_rank_and_audits(db, seeded_project, fake_slack_client):
    kid = await _insert_knowledge(db, seeded_project)
    h = FeedbackHandler(db, fake_slack_client)

    ack_calls = []

    async def ack():
        ack_calls.append(1)

    body = {
        "user": {"id": "U-MEMBER"},
        "actions": [{"action_id": f"kb_fb_up:{kid}:q1"}],
    }
    await h.handle_button(ack=ack, body=body)

    async with db.acquire() as conn:
        weight = await conn.fetchval(
            "SELECT rank_weight FROM org_knowledge WHERE id=$1", kid
        )
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM kb_feedback WHERE knowledge_id=$1 AND kind='up'",
            kid,
        )
        audits = await conn.fetchval(
            "SELECT COUNT(*) FROM kb_audit_log WHERE action='feedback_up' AND subject_id=$1",
            str(kid),
        )
    assert weight == 1.0
    assert n == 1
    assert audits == 1
    assert ack_calls == [1]


async def test_downvote_over_threshold_enqueues_rereview(
    db, seeded_project, fake_slack_client
):
    kid = await _insert_knowledge(db, seeded_project)
    h = FeedbackHandler(db, fake_slack_client)

    async def ack():
        pass

    for i in range(_RE_REVIEW_FLAG_THRESHOLD + 1):
        body = {
            "user": {"id": f"U-{i}"},
            "actions": [{"action_id": f"kb_fb_down:{kid}:q{i}"}],
        }
        await h.handle_button(ack=ack, body=body)

    async with db.acquire() as conn:
        flags = await conn.fetchval(
            "SELECT flag_count FROM org_knowledge WHERE id=$1", kid
        )
        has_rereview = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM promotion_candidates "
            "WHERE extracted_from = 'rereview' "
            "AND proposed_title LIKE '%re-review%')"
        )
    assert flags == _RE_REVIEW_FLAG_THRESHOLD + 1
    assert has_rereview is True


async def test_bookmark_inserts_fast_track_candidate(
    db, seeded_project, fake_slack_client
):
    kid = await _insert_knowledge(db, seeded_project)
    h = FeedbackHandler(db, fake_slack_client)

    async def ack():
        pass

    body = {
        "user": {"id": "U-MEMBER"},
        "actions": [{"action_id": f"kb_fb_bookmark:{kid}:q1"}],
        "message": {"text": "original answer text"},
    }
    await h.handle_button(ack=ack, body=body)

    async with db.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT COUNT(*) FROM promotion_candidates "
            "WHERE extracted_from='bookmark_fast_track' "
            "AND proposed_body LIKE '%original answer%'"
        )
    assert exists == 1
