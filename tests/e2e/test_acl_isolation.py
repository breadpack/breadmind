"""Task 22: E2E ACL isolation — cross-project + private-channel cases.

Covers the two enforcement rules from spec §7.3:

1. Cross-project: a user who belongs to only project B cannot retrieve
   knowledge from project A even when the query references A explicitly.
2. Private-channel: a channel whose ``visibility`` is
   ``channel_members_only`` restricts its knowledge to Slack channel
   members. Non-members must not see that content in KB answers.

Both tests drive the full ``QueryPipeline.build_for_e2e`` pipeline and
assert on the Slack-posted text surface.
"""
from __future__ import annotations

import pytest

from breadmind.kb.query_pipeline import QueryPipeline


@pytest.mark.asyncio
async def test_project_a_user_cannot_see_project_b_kb(db, redis, slack, llm):
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    # U-PILOT-05 belongs to pilot-beta only.
    await pipe.handle_slack_mention(
        user_id="U-PILOT-05", channel_id="C-BETA-GENERAL",
        text="<@BREADMIND> 알파 프로젝트 결제 모듈 메모리 누수?",
    )
    reply = slack.posted[-1]["text"]
    assert "CL 12345" not in reply
    assert "근거 부족" in reply or "🔴" in reply


@pytest.mark.asyncio
async def test_private_channel_kb_invisible_to_non_member(db, redis, slack, llm):
    # C-ALPHA-HR is channel_members_only and U-PILOT-02 is NOT a member.
    slack.set_channel_members("C-ALPHA-HR", {"U-PILOT-00"})
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-02", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> HR 팀 비공개 결정사항 요약해",
    )
    assert "HR" not in slack.posted[-1]["text"].upper() or "🔴" in slack.posted[-1]["text"]
