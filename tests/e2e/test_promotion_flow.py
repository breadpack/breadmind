"""Task 20: E2E promotion flow — Slack thread -> review -> approve -> query.

Drives the promotion lifecycle through ``KnowledgeExtractor.build_for_e2e``
and ``ReviewQueue.build_for_e2e`` facades, then queries via the same
``QueryPipeline.build_for_e2e`` used in Task 19 to confirm the approved
knowledge becomes discoverable.
"""
from __future__ import annotations

import pytest

from breadmind.kb.extractor import KnowledgeExtractor
from breadmind.kb.query_pipeline import QueryPipeline
from breadmind.kb.review_queue import ReviewQueue


@pytest.mark.asyncio
async def test_slack_thread_to_kb_roundtrip(db, redis, slack, llm):
    llm.script = {"노하우": "재사용 가능 노하우 후보."}
    extractor = KnowledgeExtractor.build_for_e2e(db=db, llm=llm)
    cand_id = await extractor.extract_from_thread(
        project_name="pilot-alpha",
        thread_text="오늘 클라 빌드 실패 원인은 캐시였다. 정리해 두자.",
        user_id="U-PILOT-00",
    )
    assert cand_id > 0

    queue = ReviewQueue.build_for_e2e(db=db, slack=slack)
    await queue.notify_lead(cand_id)
    assert slack.posted, "lead must receive notification"

    knowledge_id = await queue.approve(
        candidate_id=cand_id, reviewer="U-PILOT-00", source_channel="C-ALPHA-GENERAL",
    )
    assert knowledge_id > 0

    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-01", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 클라 빌드 실패 원인 정리된 게 있어?",
    )
    assert "캐시" in slack.posted[-1]["text"]
