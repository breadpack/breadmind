import pytest

from tests.e2e.fixtures.slack import FakeSlackClient
from tests.e2e.fixtures.llm import StubLLM


@pytest.mark.asyncio
async def test_team_join_triggers_consent_dm():
    from breadmind.kb.onboarding import OnboardingService

    slack = FakeSlackClient()
    retriever = _StubRetriever(items=[])
    llm_router = StubLLM(script={"onboarding": "summary"})

    svc = OnboardingService(slack_client=slack, retriever=retriever, llm_router=llm_router)
    await svc.on_team_join(event={"user": "U-NEW", "team": "T-PILOT-ALPHA"})

    assert slack.dms, "must DM the new user"
    assert slack.dms[-1]["user"] == "U-NEW"
    assert "동의" in slack.dms[-1]["text"]


@pytest.mark.asyncio
async def test_consent_accept_summarises_top_n_onboarding_items():
    from breadmind.kb.onboarding import OnboardingService

    slack = FakeSlackClient()
    items = [
        {"id": 1, "title": "Dev setup", "body": "Install Python 3.12..."},
        {"id": 2, "title": "Codebase tour", "body": "src/ is split by domain..."},
        {"id": 3, "title": "How to PR", "body": "Open PR against master..."},
    ]
    retriever = _StubRetriever(items=items)
    llm = StubLLM(script={"Dev setup": "A", "Codebase tour": "B", "How to PR": "C"})

    svc = OnboardingService(slack_client=slack, retriever=retriever, llm_router=llm,
                            top_n=3)
    await svc.on_team_join({"user": "U-NEW", "team": "T-PILOT-ALPHA"})
    await svc.on_consent(user_id="U-NEW", accepted=True)

    texts = [d["text"] for d in slack.dms]
    assert any("Dev setup" in t for t in texts)
    assert any("Codebase tour" in t for t in texts)
    assert any("How to PR" in t for t in texts)


@pytest.mark.asyncio
async def test_consent_reject_sends_no_summaries():
    from breadmind.kb.onboarding import OnboardingService

    slack = FakeSlackClient()
    retriever = _StubRetriever(items=[{"id": 1, "title": "x", "body": "y"}])
    svc = OnboardingService(slack_client=slack, retriever=retriever,
                            llm_router=StubLLM())
    await svc.on_team_join({"user": "U-NEW", "team": "T-PILOT-ALPHA"})
    await svc.on_consent(user_id="U-NEW", accepted=False)
    assert len(slack.dms) == 1


class _StubRetriever:
    def __init__(self, items):
        self.items = items

    async def onboarding_items(self, team_id: str, limit: int):
        return self.items[:limit]
