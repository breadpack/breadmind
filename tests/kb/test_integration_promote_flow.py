"""End-to-end: resolved Slack thread → extractor → approve → org_knowledge (Task 18)."""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone

from breadmind.kb.extraction_triggers import process_thread_resolved
from breadmind.kb.slack_review_handlers import handle_approve_action


async def test_resolved_thread_to_approved_knowledge(
    db, seeded_project, fake_slack_client, fake_llm_router, fake_sensitive,
    monkeypatch,
):
    # Stub embedding
    async def fake_embed(text: str):
        return [0.2] * 384

    from breadmind.kb import extraction_triggers as trig
    from breadmind.kb import review_queue as rq_mod

    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)
    monkeypatch.setattr(trig, "_build_llm_router", lambda: fake_llm_router)
    monkeypatch.setattr(trig, "_build_sensitive", lambda: fake_sensitive)
    monkeypatch.setattr(trig, "_build_slack_client", lambda: fake_slack_client)
    monkeypatch.setattr(trig, "_build_db", lambda: db)

    fake_llm_router.script = [_json.dumps({"candidates": [{
        "proposed_title": "How to restart the billing queue",
        "proposed_body": "Run `make queue-restart` then verify with `make health`.",
        "proposed_category": "howto",
        "confidence": 0.92,
    }]})]

    # Provide conversations_replies on the fake client
    now_ts = datetime.now(timezone.utc).timestamp()
    async def fake_replies(channel, ts, **kwargs):
        return {
            "ok": True,
            "messages": [
                {
                    "ts": str(now_ts),
                    "user": "U-AUTHOR",
                    "text": "resolved",
                    "reactions": [{"name": "white_check_mark", "count": 1}],
                },
            ],
        }
    fake_slack_client.conversations_replies = fake_replies

    # 1. Extract → enqueue
    result = await process_thread_resolved(
        channel_id="C1", thread_ts="1.0", project_id=str(seeded_project)
    )
    assert result["candidates_enqueued"] == 1

    # 2. Lead approves via Slack button
    async with db.acquire() as conn:
        cid = await conn.fetchval(
            "SELECT id FROM promotion_candidates WHERE project_id=$1",
            seeded_project,
        )

    from breadmind.kb.review_queue import ReviewQueue
    queue = ReviewQueue(db, fake_slack_client)

    async def ack():
        pass
    await handle_approve_action(
        ack=ack,
        body={
            "user": {"id": "U-LEAD"},
            "actions": [{"action_id": f"kb_review_approve:{cid}"}],
        },
        client=fake_slack_client,
        queue=queue,
    )

    # 3. Verify org_knowledge + audit
    async with db.acquire() as conn:
        kid = await conn.fetchval(
            "SELECT id FROM org_knowledge "
            "WHERE title='How to restart the billing queue'"
        )
        audit_actions = [r["action"] for r in await conn.fetch(
            "SELECT action FROM kb_audit_log WHERE project_id=$1", seeded_project
        )]
    assert kid is not None
    assert "enqueue_candidate" in audit_actions
    assert "promote" in audit_actions
    # DM to contributor sent
    assert any("U-AUTHOR" in str(d.get("channel", "")) for d in fake_slack_client.dms)
