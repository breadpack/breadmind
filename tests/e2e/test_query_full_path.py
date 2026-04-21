"""Task 19: E2E query full-path — all three confidence buckets.

Drives ``QueryPipeline.build_for_e2e`` through a real testcontainers Postgres
(via the session-scoped ``db`` fixture) with stub LLM + Slack clients. Each
test asserts on the surface format posted to FakeSlackClient.posted.
"""
from __future__ import annotations

import pytest

from breadmind.kb.query_pipeline import QueryPipeline


@pytest.mark.asyncio
async def test_mention_yields_answer_with_citation_and_high_confidence(
    db, redis, slack, llm,
):
    llm.script = {"결제 모듈": "누수는 CL 12345에서 패치되었습니다."}
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)

    await pipe.handle_slack_mention(
        user_id="U-PILOT-00", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 결제 모듈 메모리 누수 어떻게 고쳤어?",
    )

    post = slack.posted[-1]
    assert "CL 12345" in post["text"]
    assert "📎" in post["text"] or "출처" in post["text"]
    assert "🟢" in post["text"]


@pytest.mark.asyncio
async def test_medium_confidence_adds_warning_icon(db, redis, slack, llm):
    llm.script = {}
    pipe = QueryPipeline.build_for_e2e(
        db=db, redis=redis, slack=slack, llm=llm, force_confidence="medium",
    )
    await pipe.handle_slack_mention(
        user_id="U-PILOT-01", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> CI 파이프라인 확장 방법?",
    )
    assert "🟡" in slack.posted[-1]["text"] or "🔴" in slack.posted[-1]["text"]


@pytest.mark.asyncio
async def test_low_confidence_returns_search_only(db, redis, slack, llm):
    llm.script = {}
    pipe = QueryPipeline.build_for_e2e(
        db=db, redis=redis, slack=slack, llm=llm, force_confidence="low",
    )
    await pipe.handle_slack_mention(
        user_id="U-PILOT-02", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 알 수 없는 질문입니다",
    )
    assert "담당자 확인 권장" in slack.posted[-1]["text"]
