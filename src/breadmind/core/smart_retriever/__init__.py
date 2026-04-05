"""SmartRetriever: RAG + KG retrieval engine for skills and context.

This package splits the retriever into focused components:
- common: Shared utilities (extract_keywords, data classes, RRF scoring)
- strategies: Search strategies (vector, KG, keyword)
- indexer: Skill and task result indexing (SkillIndexer)
- __init__: SmartRetriever orchestrator (this file)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from breadmind.core.smart_retriever.common import (
    ContextItem,
    ScoredSkill,
    _rrf_score,
    extract_keywords,
)
from breadmind.core.smart_retriever.indexer import SkillIndexer
from breadmind.core.smart_retriever.strategies import (
    _extract_skill_name_from_tags,
    keyword_search_skills,
    kg_search_skills,
    vector_search_skills,
)

if TYPE_CHECKING:
    from breadmind.core.skill_store import SkillStore
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)

# Re-export public API for backward compatibility
__all__ = [
    "SmartRetriever",
    "SkillIndexer",
    "ScoredSkill",
    "ContextItem",
    "extract_keywords",
    "_rrf_score",
]


class SmartRetriever:
    """RAG + KG retrieval engine for skills and context."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        skill_store: SkillStore,
        db: Database | None = None,
    ):
        self._embedding = embedding_service
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._skill_store = skill_store
        self._db = db
        self._indexer = SkillIndexer(
            embedding_service=embedding_service,
            episodic_memory=episodic_memory,
            semantic_memory=semantic_memory,
            db=db,
        )

    async def retrieve_skills(
        self, query: str, token_budget: int = 2000, limit: int = 5,
    ) -> list[ScoredSkill]:
        """Retrieve most relevant skills using vector + KG + keyword search with RRF."""
        vector_ranked: list[tuple[str, float]] = []  # (skill_name, raw_score)
        kg_ranked: list[tuple[str, float]] = []
        keyword_ranked: list[tuple[str, float]] = []

        # Source 1: Vector search
        query_embedding = await self._embedding.encode(query)
        if query_embedding is not None:
            vector_ranked = await vector_search_skills(
                self._embedding, self._episodic, self._db,
                query_embedding, limit=10,
            )

        # Source 2: KG graph search
        kg_ranked = await kg_search_skills(self._semantic, query, limit=10)

        # Source 3: Keyword search (always included, not just fallback)
        keyword_ranked = await keyword_search_skills(
            self._skill_store, query, limit=10,
        )

        # If all sources empty, use SkillStore fallback
        if not vector_ranked and not kg_ranked and not keyword_ranked:
            return await self._keyword_fallback(query, token_budget, limit)

        # RRF merge
        rrf_scores: dict[str, float] = {}
        sources: dict[str, set] = {}

        for rank, (name, _) in enumerate(vector_ranked):
            rrf_scores[name] = rrf_scores.get(name, 0) + _rrf_score(rank)
            sources.setdefault(name, set()).add("vector")

        for rank, (name, _) in enumerate(kg_ranked):
            rrf_scores[name] = rrf_scores.get(name, 0) + _rrf_score(rank)
            sources.setdefault(name, set()).add("kg")

        for rank, (name, _) in enumerate(keyword_ranked):
            rrf_scores[name] = rrf_scores.get(name, 0) + _rrf_score(rank)
            sources.setdefault(name, set()).add("keyword")

        # Build ScoredSkill list
        scored = []
        for skill_name, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True):
            skill = await self._skill_store.get_skill(skill_name)
            if skill is None:
                continue
            src = sources.get(skill_name, set())
            source_str = "+".join(sorted(src)) if len(src) > 1 else next(iter(src))
            token_est = len(skill.prompt_template) // 4 if skill.prompt_template else 0
            scored.append(ScoredSkill(skill=skill, score=score, token_estimate=token_est, source=source_str))

        return self._apply_token_budget(scored, token_budget, limit)

    async def retrieve_context(
        self, query: str, token_budget: int = 1000, limit: int = 5,
    ) -> list[ContextItem]:
        """Retrieve relevant past task history."""
        items: list[ContextItem] = []

        query_embedding = await self._embedding.encode(query)
        if (
            query_embedding is not None
            and self._db
            and await self._db.has_pgvector()
        ):
            # pgvector search for task history
            results = await self._db.search_by_embedding(
                query_embedding, limit=limit, tag_filter="task_history",
            )
            for note, score in results:
                items.append(ContextItem(
                    content=note.content, score=score,
                    source="episodic",
                    token_estimate=len(note.content) // 4,
                ))
        elif query_embedding is not None:
            # In-memory similarity search
            all_notes = await self._episodic.get_all_notes()
            task_notes = [
                n for n in all_notes if "task_history" in (n.tags or [])
            ]
            scored_notes = []
            for note in task_notes:
                if note.embedding:
                    sim = self._embedding.cosine_similarity(
                        query_embedding, note.embedding,
                    )
                    scored_notes.append((note, sim))
            scored_notes.sort(key=lambda x: x[1], reverse=True)
            for note, score in scored_notes[:limit]:
                items.append(ContextItem(
                    content=note.content, score=score,
                    source="episodic",
                    token_estimate=len(note.content) // 4,
                ))
        else:
            # Keyword fallback
            keywords = extract_keywords(query)
            if keywords:
                notes = await self._episodic.search_by_keywords(
                    keywords, limit=limit,
                )
                task_notes = [
                    n for n in notes if "task_history" in (n.tags or [])
                ]
                for note in task_notes:
                    items.append(ContextItem(
                        content=note.content, score=0.5,
                        source="episodic",
                        token_estimate=len(note.content) // 4,
                    ))

        return self._apply_token_budget_context(items, token_budget, limit)

    async def index_skill(self, skill) -> None:
        """Index a skill in EpisodicMemory and KG. Delegates to SkillIndexer."""
        await self._indexer.index_skill(skill)

    async def index_task_result(
        self, role: str, task_desc: str, result_summary: str, success: bool,
    ) -> None:
        """Index a completed task. Delegates to SkillIndexer."""
        await self._indexer.index_task_result(role, task_desc, result_summary, success)

    # --- Private methods ---

    async def _keyword_fallback(
        self, query: str, token_budget: int, limit: int,
    ) -> list[ScoredSkill]:
        """Fallback to keyword matching via SkillStore."""
        skills = await self._skill_store.find_matching_skills(
            query, limit=limit,
        )
        scored = []
        for skill in skills:
            token_est = (
                len(skill.prompt_template) // 4
                if skill.prompt_template
                else 0
            )
            scored.append(ScoredSkill(
                skill=skill, score=0.3,
                token_estimate=token_est, source="keyword",
            ))
        return self._apply_token_budget(scored, token_budget, limit)

    @staticmethod
    def _extract_skill_name_from_tags(tags: list[str] | None) -> str | None:
        """Extract skill name from tags like ['skill:pod_check']."""
        return _extract_skill_name_from_tags(tags)

    @staticmethod
    def _apply_token_budget(
        items: list[ScoredSkill], budget: int, limit: int,
    ) -> list[ScoredSkill]:
        selected: list[ScoredSkill] = []
        used = 0
        for item in items:
            if len(selected) >= limit:
                break
            if used + item.token_estimate > budget:
                continue
            selected.append(item)
            used += item.token_estimate
        return selected

    @staticmethod
    def _apply_token_budget_context(
        items: list[ContextItem], budget: int, limit: int,
    ) -> list[ContextItem]:
        selected: list[ContextItem] = []
        used = 0
        for item in items:
            if len(selected) >= limit:
                break
            if used + item.token_estimate > budget:
                continue
            selected.append(item)
            used += item.token_estimate
        return selected

    # --- Expose strategies as private methods for test compatibility ---

    async def _vector_search_skills(
        self, query_embedding: list[float], limit: int = 10,
    ) -> list[tuple[str, float]]:
        return await vector_search_skills(
            self._embedding, self._episodic, self._db,
            query_embedding, limit=limit,
        )

    async def _kg_search_skills(
        self, query: str, limit: int = 10,
    ) -> list[tuple[str, float]]:
        return await kg_search_skills(self._semantic, query, limit=limit)

    async def _keyword_search_skills(
        self, query: str, limit: int = 10,
    ) -> list[tuple[str, float]]:
        return await keyword_search_skills(
            self._skill_store, query, limit=limit,
        )
