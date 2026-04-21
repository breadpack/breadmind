"""New-member onboarding flow (spec §6.5).

Subscribes to Slack `team_join`, DMs the user for consent, and on accept
sequentially summarizes the top-N `org_knowledge(category='onboarding')`
items for the user's project.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class OnboardingRetriever(Protocol):
    async def onboarding_items(self, team_id: str, limit: int) -> list[dict]: ...


class LLMClient(Protocol):
    async def complete(self, prompt: str, hits: list) -> tuple[Any, Any]: ...


@dataclass
class OnboardingService:
    slack_client: Any
    retriever: OnboardingRetriever
    llm_router: LLMClient
    top_n: int = 5
    _pending: dict[str, str] = field(default_factory=dict)

    async def on_team_join(self, event: dict) -> None:
        user = event["user"]
        team = event.get("team", "")
        self._pending[user] = team
        await self._dm(
            user,
            "환영합니다 👋 BreadMind가 온보딩 요약을 보내드릴까요?\n"
            "동의하시면 `/breadmind onboard yes` 라고 답해주세요.",
        )

    async def on_consent(self, user_id: str, accepted: bool) -> None:
        team = self._pending.pop(user_id, None)
        if not accepted or team is None:
            return
        items = await self.retriever.onboarding_items(team_id=team, limit=self.top_n)
        for item in items:
            prompt = f"{item['title']}\n\n{item['body']}\n\n3줄로 요약"
            draft, _ = await self.llm_router.complete(prompt, [])
            summary = getattr(draft, "text", str(draft))
            await self._dm(user_id, f"*{item['title']}*\n{summary}")

    async def _dm(self, user_id: str, text: str) -> None:
        if hasattr(self.slack_client, "dm"):
            await self.slack_client.dm(user_id, text)
            return
        opened = await self.slack_client.conversations_open(users=user_id)
        channel = opened["channel"]["id"]
        await self.slack_client.chat_postMessage(channel=channel, text=text)
