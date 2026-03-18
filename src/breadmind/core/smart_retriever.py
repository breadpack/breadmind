from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.core.skill_store import SkillStore
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "and", "but", "or", "if", "while", "that", "this", "these", "those",
    "it", "its", "my", "your", "his", "her", "our", "their", "what",
    "which", "who", "whom", "check", "get", "set", "run", "use",
})

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9._-]+")


def _rrf_score(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion score. k=60 is the standard constant."""
    return 1.0 / (rank + k)


def extract_keywords(text: str) -> list[str]:
    """Extract keywords from text, filtering stopwords."""
    words = _WORD_PATTERN.findall(text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        if len(w) >= 2 and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result


@dataclass
class ScoredSkill:
    skill: object  # Skill from skill_store
    score: float
    token_estimate: int
    source: str  # "vector" | "kg" | "both"


@dataclass
class ContextItem:
    content: str
    score: float
    source: str  # "episodic" | "kg"
    token_estimate: int


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
        self._index_lock = asyncio.Lock()

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
            vector_ranked = await self._vector_search_skills(query_embedding, limit=10)

        # Source 2: KG graph search
        kg_ranked = await self._kg_search_skills(query, limit=10)

        # Source 3: Keyword search (always included, not just fallback)
        keyword_ranked = await self._keyword_search_skills(query, limit=10)

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
        """Index a skill in EpisodicMemory and KG."""
        async with self._index_lock:
            # Embed and store in EpisodicMemory
            text = (
                f"{skill.name}: {skill.description}. "
                f"{skill.prompt_template[:200] if skill.prompt_template else ''}"
            )
            embedding = await self._embedding.encode(text)

            note = await self._episodic.add_note(
                content=text,
                keywords=(
                    list(skill.trigger_keywords)
                    if skill.trigger_keywords
                    else []
                ),
                tags=[f"skill:{skill.name}"],
                context_description=f"Skill: {skill.name}",
                embedding=embedding,
            )

            # Store vector in pgvector if available
            if (
                embedding
                and self._db
                and await self._db.has_pgvector()
                and note.id
            ):
                try:
                    await self._db.save_note_with_vector(note, embedding)
                except Exception as e:
                    logger.warning(
                        "Failed to store vector for skill %s: %s",
                        skill.name, e,
                    )

            # Create KG entities and relations
            from breadmind.storage.models import KGEntity, KGRelation

            skill_entity = KGEntity(
                id=f"skill:{skill.name}",
                entity_type="skill",
                name=skill.name,
                properties={
                    "description": skill.description,
                    "source": getattr(skill, "source", "manual"),
                },
            )
            await self._semantic.add_entity(skill_entity)

            # Relations from trigger keywords
            for kw in skill.trigger_keywords or []:
                domain_entity = KGEntity(
                    id=f"domain:{kw}",
                    entity_type="domain",
                    name=kw,
                )
                await self._semantic.add_entity(domain_entity)
                await self._semantic.add_relation(KGRelation(
                    source_id=f"skill:{skill.name}",
                    target_id=f"domain:{kw}",
                    relation_type="related_to",
                ))

    async def index_task_result(
        self, role: str, task_desc: str, result_summary: str, success: bool,
    ) -> None:
        """Index a completed task in EpisodicMemory and KG."""
        async with self._index_lock:
            text = f"[{role}] {task_desc}: {result_summary}"
            embedding = await self._embedding.encode(text)

            note = await self._episodic.add_note(
                content=text,
                keywords=extract_keywords(task_desc),
                tags=["task_history", f"role:{role}"],
                context_description=f"Task by {role}",
                embedding=embedding,
            )

            if (
                embedding
                and self._db
                and await self._db.has_pgvector()
                and note.id
            ):
                try:
                    await self._db.save_note_with_vector(note, embedding)
                except Exception as e:
                    logger.warning("Failed to store task vector: %s", e)

            # KG relation
            from breadmind.storage.models import KGEntity, KGRelation

            task_hash = hashlib.sha256(
                f"{role}:{task_desc}".encode(),
            ).hexdigest()[:12]

            role_entity = KGEntity(
                id=f"role:{role}", entity_type="role", name=role,
            )
            await self._semantic.add_entity(role_entity)

            task_entity = KGEntity(
                id=f"task:{task_hash}",
                entity_type="task_history",
                name=task_desc[:100],
                properties={"success": success, "role": role},
            )
            await self._semantic.add_entity(task_entity)

            await self._semantic.add_relation(KGRelation(
                source_id=f"role:{role}",
                target_id=f"task:{task_hash}",
                relation_type="executed",
                weight=1.0 if success else 0.3,
            ))

    # --- Private methods ---

    async def _vector_search_skills(
        self, query_embedding: list[float], limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Search skills by vector similarity."""
        results: list[tuple[str, float]] = []

        if self._db and await self._db.has_pgvector():
            db_results = await self._db.search_by_embedding(
                query_embedding, limit=limit,
            )
            for note, score in db_results:
                skill_name = self._extract_skill_name_from_tags(note.tags)
                if skill_name:
                    results.append((skill_name, score))
        else:
            # In-memory cosine similarity
            all_notes = await self._episodic.get_all_notes()
            scored = []
            for note in all_notes:
                skill_name = self._extract_skill_name_from_tags(note.tags)
                if skill_name and note.embedding:
                    sim = self._embedding.cosine_similarity(
                        query_embedding, note.embedding,
                    )
                    scored.append((skill_name, sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            results = scored[:limit]

        return results

    async def _kg_search_skills(
        self, query: str, limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Search skills by KG graph traversal."""
        keywords = extract_keywords(query)
        if not keywords:
            return []

        # Find domain entities matching keywords
        skill_scores: dict[str, float] = {}
        for kw in keywords:
            entities = await self._semantic.find_entities(name_contains=kw)
            for entity in entities:
                # Walk relations to find connected skills
                relations = await self._semantic.get_relations(
                    entity.id, direction="both",
                )
                for rel in relations:
                    other_id = (
                        rel.target_id
                        if rel.source_id == entity.id
                        else rel.source_id
                    )
                    if other_id.startswith("skill:"):
                        skill_name = other_id[6:]  # Remove "skill:" prefix
                        score = rel.weight * entity.weight
                        skill_scores[skill_name] = max(
                            skill_scores.get(skill_name, 0), score,
                        )

        # Normalize scores to 0-1
        if skill_scores:
            max_score = max(skill_scores.values())
            if max_score > 0:
                skill_scores = {
                    k: v / max_score for k, v in skill_scores.items()
                }

        sorted_skills = sorted(
            skill_scores.items(), key=lambda x: x[1], reverse=True,
        )
        return sorted_skills[:limit]

    async def _keyword_search_skills(
        self, query: str, limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Search skills by keyword matching. Returns (skill_name, score) pairs."""
        keywords = extract_keywords(query)
        if not keywords:
            return []

        all_skills = await self._skill_store.list_skills()
        scored = []
        for skill in all_skills:
            kw_set = set(k.lower() for k in (skill.trigger_keywords or []))
            desc_words = set(skill.description.lower().split()) if skill.description else set()
            query_set = set(keywords)
            kw_matches = len(query_set & kw_set)
            desc_matches = len(query_set & desc_words)
            score = kw_matches * 2.0 + desc_matches
            if score > 0:
                scored.append((skill.name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

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
        if not tags:
            return None
        for tag in tags:
            if tag.startswith("skill:"):
                return tag[6:]
        return None

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
