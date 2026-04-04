"""v2 EpisodicMemory: 경험 기반 메모리."""
from __future__ import annotations

from typing import TYPE_CHECKING

from breadmind.core.protocols import Episode

if TYPE_CHECKING:
    from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend


class EpisodicMemory:
    """에피소딕 메모리. backend이 없으면 인메모리, 있으면 PostgreSQL."""

    def __init__(
        self,
        max_episodes: int = 500,
        backend: PgMemoryBackend | None = None,
    ) -> None:
        self._episodes: list[Episode] = []
        self._max = max_episodes
        self._backend = backend

    async def episodic_search(self, query: str, limit: int = 5) -> list[Episode]:
        if self._backend is not None:
            if query == "*":
                rows = await self._backend.episodic_get_recent(limit)
            else:
                keywords = query.split()
                rows = await self._backend.episodic_search(keywords, limit)
                if not rows:
                    rows = await self._backend.episodic_search_by_content(query, limit)
            return [
                Episode(
                    id=r["id"],
                    content=r["content"],
                    keywords=r["keywords"],
                    timestamp=r["timestamp"],
                    metadata=r.get("metadata", {}),
                )
                for r in rows
            ]

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
        if self._backend is not None:
            episode_dict = {
                "content": episode.content,
                "keywords": episode.keywords,
                "timestamp": episode.timestamp or None,
                "metadata": episode.metadata,
            }
            await self._backend.episodic_save(episode_dict)
            # Enforce max episodes
            count = await self._backend.episodic_count()
            if count > self._max:
                await self._backend.episodic_delete_oldest(count - self._max)
            return

        self._episodes.append(episode)
        if len(self._episodes) > self._max:
            self._episodes = self._episodes[-self._max:]

    def count(self) -> int:
        """Return episode count (in-memory only). Use count_async() with a backend."""
        return len(self._episodes)

    async def count_async(self) -> int:
        """Return episode count, works with both in-memory and backend."""
        if self._backend is not None:
            return await self._backend.episodic_count()
        return len(self._episodes)
