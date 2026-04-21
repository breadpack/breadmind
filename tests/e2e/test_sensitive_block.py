"""Task 23: E2E sensitive-category block + HR role exception.

Covers the spec §7.4 HR-compensation block: a regular user asking about
salary / compensation gets the block reply (no LLM call), while a member
of the ``hr`` project bypasses the block and goes through to an answer.
"""
from __future__ import annotations

import pytest

from breadmind.kb.query_pipeline import QueryPipeline


@pytest.mark.asyncio
async def test_hr_query_blocked_for_regular_user(db, redis, slack, llm):
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-04", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 이번 분기 우리팀 연봉 인상률 알려줘",
    )
    reply = slack.posted[-1]["text"]
    assert "민감 카테고리" in reply
    assert "#hr-inquiry" in reply
    # LLM must not have been called at all.
    assert llm.calls == []


@pytest.mark.asyncio
async def test_hr_query_allowed_for_hr_project_member(db, redis, slack, llm):
    # Seed makes U-PILOT-00 a 'lead' of pilot-alpha; extend to HR project manually.
    await db.execute(
        "INSERT INTO org_projects (name, slack_team_id) VALUES ('hr','T-HR') "
        "ON CONFLICT (name) DO NOTHING"
    )
    hr_id = await db.fetchval("SELECT id FROM org_projects WHERE name='hr'")
    await db.execute(
        "INSERT INTO org_project_members (project_id,user_id,role) "
        "VALUES ($1,'U-HR-LEAD','lead') ON CONFLICT DO NOTHING", hr_id,
    )
    llm.script = {"연봉": "HR 프로젝트 컨텍스트에서만 답변 가능."}
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    await pipe.handle_slack_mention(
        user_id="U-HR-LEAD", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 연봉 테이블 요약",
    )
    assert "HR 프로젝트" in slack.posted[-1]["text"]
