"""Search strategies for SmartRetriever: vector, knowledge graph, and keyword."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from breadmind.core.smart_retriever.common import extract_keywords

if TYPE_CHECKING:
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.core.skill_store import SkillStore
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)


async def vector_search_skills(
    embedding: EmbeddingService,
    episodic: EpisodicMemory,
    db: Database | None,
    query_embedding: list[float],
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Search skills by vector similarity."""
    results: list[tuple[str, float]] = []

    if db and await db.has_pgvector():
        db_results = await db.search_by_embedding(
            query_embedding, limit=limit,
        )
        for note, score in db_results:
            skill_name = _extract_skill_name_from_tags(note.tags)
            if skill_name:
                results.append((skill_name, score))
    else:
        # In-memory cosine similarity
        all_notes = await episodic.get_all_notes()
        scored = []
        for note in all_notes:
            skill_name = _extract_skill_name_from_tags(note.tags)
            if skill_name and note.embedding:
                sim = embedding.cosine_similarity(
                    query_embedding, note.embedding,
                )
                scored.append((skill_name, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        results = scored[:limit]

    return results


async def kg_search_skills(
    semantic: SemanticMemory,
    query: str,
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Search skills by KG graph traversal."""
    keywords = extract_keywords(query)
    if not keywords:
        return []

    # Find domain entities matching keywords
    skill_scores: dict[str, float] = {}
    for kw in keywords:
        entities = await semantic.find_entities(name_contains=kw)
        for entity in entities:
            # Walk relations to find connected skills
            relations = await semantic.get_relations(
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


async def keyword_search_skills(
    skill_store: SkillStore,
    query: str,
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Search skills by keyword matching. Returns (skill_name, score) pairs."""
    keywords = extract_keywords(query)
    if not keywords:
        return []

    all_skills = await skill_store.list_skills()
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


def _extract_skill_name_from_tags(tags: list[str] | None) -> str | None:
    """Extract skill name from tags like ['skill:pod_check']."""
    if not tags:
        return None
    for tag in tags:
        if tag.startswith("skill:"):
            return tag[6:]
    return None
