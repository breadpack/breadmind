"""Tests for review_dispatcher (Task 11)."""
from __future__ import annotations

from breadmind.kb.review_dispatcher import run_daily_digest
from breadmind.kb.review_queue import ReviewQueue
from breadmind.kb.types import ExtractedCandidate


def _candidate(pid):
    return ExtractedCandidate(
        proposed_title="t",
        proposed_body="b",
        proposed_category="howto",
        confidence=0.9,
        sources=[],
        original_user="U-AUTHOR",
        project_id=pid,
    )


async def test_daily_digest_dms_leads_when_threshold_reached(
    db, seeded_project, fake_slack_client
):
    rq = ReviewQueue(db, fake_slack_client)
    for _ in range(5):
        await rq.enqueue(_candidate(seeded_project))

    await run_daily_digest(db=db, slack_client=fake_slack_client)
    # At least one DM to U-LEAD
    lead_dms = [
        d for d in fake_slack_client.dms if "U-LEAD" in str(d.get("channel", ""))
    ]
    assert len(lead_dms) >= 1


async def test_daily_digest_no_dm_when_empty(
    db, seeded_project, fake_slack_client
):
    result = await run_daily_digest(db=db, slack_client=fake_slack_client)
    assert fake_slack_client.dms == []
    assert result == {"projects_dm": [], "backpressure_projects": []}


async def test_backpressure_pauses_extraction_over_500(
    db, seeded_project, fake_slack_client
):
    # Fast-insert 501 dummy candidates bypassing enqueue
    async with db.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO promotion_candidates
              (project_id, extracted_from, proposed_title, proposed_body,
               proposed_category, sources_json, confidence, status)
            VALUES ($1, 'test', 't', 'b', 'howto', '[]'::jsonb, 0.9, 'pending')
            """,
            [(seeded_project,)] * 501,
        )
    result = await run_daily_digest(db=db, slack_client=fake_slack_client)
    assert str(seeded_project) in result["backpressure_projects"]

    async with db.acquire() as conn:
        paused = await conn.fetchval(
            "SELECT paused FROM kb_extraction_pause WHERE project_id=$1",
            seeded_project,
        )
    assert paused is True
