"""v2 SmartRetriever: 멀티레이어 메모리 검색."""
from __future__ import annotations
from typing import Any
from breadmind.core.protocols import Episode, KGTriple


class SmartRetriever:
    """에피소딕 + 시맨틱 메모리를 통합 검색."""

    def __init__(self, episodic: Any = None, semantic: Any = None) -> None:
        self._episodic = episodic
        self._semantic = semantic

    async def retrieve(self, query: str, limit: int = 5) -> list[str]:
        results = []

        # Episodic search
        if self._episodic:
            try:
                episodes: list[Episode] = await self._episodic.episodic_search(query, limit=limit)
                for ep in episodes:
                    results.append(f"[Episode] {ep.content}")
            except Exception:
                pass

        # Semantic search — extract entities from query
        if self._semantic:
            try:
                entities = self._extract_entities(query)
                if entities:
                    triples: list[KGTriple] = await self._semantic.semantic_query(entities)
                    for t in triples[:limit]:
                        results.append(f"[Knowledge] {t.subject} {t.predicate} {t.object}")
            except Exception:
                pass

        return results[:limit]

    def _extract_entities(self, query: str) -> list[str]:
        import re
        # Extract potential entity names (capitalized words, hyphenated, technical terms)
        entities = re.findall(r'\b[A-Z][a-zA-Z0-9_-]+\b', query)
        entities += re.findall(r'\b(?:pod|node|vm|lxc|container|service|deploy)[-_]?\w*\b', query, re.I)
        return list(set(entities))[:10]
