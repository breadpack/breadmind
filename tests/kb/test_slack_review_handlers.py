"""Tests for Slack review handlers (Task 14)."""
from __future__ import annotations

from breadmind.kb.review_queue import ReviewQueue
from breadmind.kb.slack_review_handlers import (
    build_candidate_blocks,
    handle_approve_action,
    handle_reject_open_modal,
    handle_reject_submit,
)
from breadmind.kb.types import ExtractedCandidate


def _cand(pid):
    return ExtractedCandidate(
        proposed_title="how to fix X",
        proposed_body="run Y then Z",
        proposed_category="howto",
        confidence=0.9,
        sources=[],
        original_user="U-AUTHOR",
        project_id=pid,
    )


def test_build_candidate_blocks_has_four_buttons():
    blocks = build_candidate_blocks(
        candidate_id=7,
        title="t",
        body="b",
        category="howto",
        confidence=0.9,
    )
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e["action_id"] for e in action_block["elements"]]
    assert "kb_review_approve:7" in action_ids
    assert "kb_review_reject:7" in action_ids
    assert "kb_review_needs_edit:7" in action_ids
    assert "kb_review_web_edit:7" in action_ids


async def test_handle_approve_invokes_queue(
    db, seeded_project, fake_slack_client, monkeypatch
):
    async def fake_embed(text: str):
        return [0.1] * 384
    from breadmind.kb import review_queue as rq_mod
    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)

    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_cand(seeded_project))

    ack_calls = []

    async def ack():
        ack_calls.append(1)

    body = {"user": {"id": "U-LEAD"}, "actions": [{"action_id": f"kb_review_approve:{cid}"}]}
    await handle_approve_action(
        ack=ack, body=body, client=fake_slack_client, queue=rq
    )
    assert ack_calls == [1]
    async with db.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM promotion_candidates WHERE id=$1", cid
        )
    assert status == "approved"


async def test_handle_reject_opens_modal(
    db, seeded_project, fake_slack_client
):
    ack_calls = []

    async def ack():
        ack_calls.append(1)

    body = {
        "user": {"id": "U-LEAD"},
        "trigger_id": "TRIG-1",
        "actions": [{"action_id": "kb_review_reject:42"}],
    }
    await handle_reject_open_modal(ack=ack, body=body, client=fake_slack_client)
    assert ack_calls == [1]
    assert len(fake_slack_client.views_opened) == 1
    view = fake_slack_client.views_opened[0]["view"]
    assert view["callback_id"] == "kb_review_reject_modal"
    assert view["private_metadata"] == "42"


async def test_handle_reject_submit_calls_queue(
    db, seeded_project, fake_slack_client
):
    rq = ReviewQueue(db, fake_slack_client)
    cid = await rq.enqueue(_cand(seeded_project))

    async def ack():
        pass

    view = {
        "private_metadata": str(cid),
        "state": {"values": {
            "reason_block": {
                "reason_input": {"value": "duplicate of KB-3"}
            }
        }},
    }
    body = {"user": {"id": "U-LEAD"}, "view": view}
    await handle_reject_submit(ack=ack, body=body, view=view, queue=rq)

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, reviewer FROM promotion_candidates WHERE id=$1", cid
        )
    assert row["status"] == "rejected"
    assert row["reviewer"] == "U-LEAD"
