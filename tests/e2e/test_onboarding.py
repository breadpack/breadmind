import pytest

from breadmind.kb.onboarding import OnboardingService


class _DBRetriever:
    def __init__(self, db):
        self.db = db

    async def onboarding_items(self, team_id: str, limit: int):
        rows = await self.db.fetch(
            "SELECT k.id, k.title, k.body FROM org_knowledge k "
            "JOIN org_projects p ON p.id = k.project_id "
            "WHERE p.slack_team_id = $1 AND k.category = 'onboarding' "
            "ORDER BY k.id LIMIT $2",
            team_id, limit,
        )
        return [dict(r) for r in rows]


@pytest.mark.asyncio
async def test_new_member_receives_onboarding_dm(db, slack, llm):
    llm.script = {"sample": "짧은 요약"}
    svc = OnboardingService(slack_client=slack, retriever=_DBRetriever(db),
                            llm_router=llm, top_n=3)
    await svc.on_team_join({"user": "U-NEW-JOINER", "team": "T-PILOT-ALPHA"})
    assert slack.dms[-1]["user"] == "U-NEW-JOINER"
    await svc.on_consent(user_id="U-NEW-JOINER", accepted=True)
    summary_dms = [d for d in slack.dms if d["user"] == "U-NEW-JOINER"]
    assert len(summary_dms) >= 4  # 1 consent + 3 summaries
