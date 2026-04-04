"""v2 EpisodicMemory: 경험 기반 메모리."""
from __future__ import annotations
from breadmind.core.protocols import Episode


class EpisodicMemory:
    """인메모리 에피소딕 메모리."""

    def __init__(self, max_episodes: int = 500) -> None:
        self._episodes: list[Episode] = []
        self._max = max_episodes

    async def episodic_search(self, query: str, limit: int = 5) -> list[Episode]:
        if query == "*":
            return self._episodes[-limit:]
        query_lower = query.lower()
        scored = []
        for ep in self._episodes:
            score = 0
            for kw in ep.keywords:
                if kw.lower() in query_lower or query_lower in kw.lower():
                    score += 1
            if query_lower in (ep.content or "").lower():
                score += 2
            if score > 0:
                scored.append((score, ep))
        scored.sort(key=lambda x: -x[0])
        return [ep for _, ep in scored[:limit]]

    async def episodic_save(self, episode: Episode) -> None:
        self._episodes.append(episode)
        if len(self._episodes) > self._max:
            self._episodes = self._episodes[-self._max:]

    def count(self) -> int:
        return len(self._episodes)
