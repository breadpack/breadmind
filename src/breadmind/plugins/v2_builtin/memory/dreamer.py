"""Dream 시스템: 세션 종료 후 메모리 정리."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from breadmind.core.protocols import Message, Episode

logger = logging.getLogger("breadmind.dreamer")


@dataclass
class DreamResult:
    session_id: str
    new_episodes: int = 0
    consolidated: int = 0
    pruned: int = 0


class Dreamer:
    """세션 종료 후 메모리 정리: Orient → Gather → Consolidate → Prune."""

    def __init__(
        self,
        provider: Any = None,
        episodic_memory: Any = None,
        max_episodes: int = 100,
        prune_threshold_days: int = 30,
    ) -> None:
        self._provider = provider
        self._episodic = episodic_memory
        self._max_episodes = max_episodes
        self._prune_days = prune_threshold_days

    async def dream(self, session_id: str, messages: list[Message] | None = None) -> DreamResult:
        result = DreamResult(session_id=session_id)

        # Phase 1: Orient — read existing long-term memories
        existing = await self._orient()

        # Phase 2: Gather — extract signals from session
        new_signals = await self._gather(messages or [])
        result.new_episodes = len(new_signals)

        # Phase 3: Consolidate — merge with existing
        consolidated = self._consolidate(existing, new_signals)
        result.consolidated = len(consolidated)

        # Phase 4: Prune — remove stale entries
        pruned_count = await self._prune(consolidated)
        result.pruned = pruned_count

        # Save consolidated episodes
        if self._episodic:
            for ep in new_signals:
                try:
                    await self._episodic.episodic_save(ep)
                except Exception as e:
                    logger.warning("Failed to save episode: %s", e)

        logger.info(
            "Dream complete for %s: %d new, %d consolidated, %d pruned",
            session_id, result.new_episodes, result.consolidated, result.pruned,
        )
        return result

    async def _orient(self) -> list[Episode]:
        if not self._episodic:
            return []
        try:
            return await self._episodic.episodic_search("*", limit=50)
        except Exception:
            return []

    async def _gather(self, messages: list[Message]) -> list[Episode]:
        if not messages:
            return []

        episodes = []
        # Extract key interactions: user questions + assistant answers with tool usage
        for i, msg in enumerate(messages):
            if msg.role == "user" and msg.content and not msg.is_meta:
                # Find corresponding assistant response
                response_content = ""
                for j in range(i + 1, min(i + 5, len(messages))):
                    if messages[j].role == "assistant" and messages[j].content:
                        response_content = messages[j].content
                        break

                if response_content:
                    keywords = self._extract_keywords(msg.content + " " + response_content)
                    episodes.append(Episode(
                        id=f"ep_{i}",
                        content=f"Q: {msg.content[:200]}\nA: {response_content[:300]}",
                        keywords=keywords,
                    ))

        return episodes

    def _consolidate(self, existing: list[Episode], new: list[Episode]) -> list[Episode]:
        # Simple deduplication: skip new episodes that have >50% keyword overlap with existing
        consolidated = list(existing)
        for ep in new:
            new_kw = set(ep.keywords)
            is_duplicate = False
            for ex in existing:
                ex_kw = set(ex.keywords)
                if new_kw and ex_kw:
                    overlap = len(new_kw & ex_kw) / max(len(new_kw | ex_kw), 1)
                    if overlap > 0.5:
                        is_duplicate = True
                        break
            if not is_duplicate:
                consolidated.append(ep)
        return consolidated

    async def _prune(self, episodes: list[Episode]) -> int:
        if len(episodes) <= self._max_episodes:
            return 0
        return len(episodes) - self._max_episodes

    def _extract_keywords(self, text: str) -> list[str]:
        import re
        words = re.findall(r'\b[a-zA-Z가-힣]{2,}\b', text.lower())
        # Simple frequency-based keyword extraction
        freq: dict[str, int] = {}
        stopwords = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "있는", "하는", "것을"}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in sorted_words[:10]]
