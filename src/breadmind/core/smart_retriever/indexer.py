"""Skill and task indexing for SmartRetriever."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING

from breadmind.core.smart_retriever.common import extract_keywords

if TYPE_CHECKING:
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)


class SkillIndexer:
    """Indexes skills and task results in EpisodicMemory and KG."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        db: Database | None = None,
    ):
        self._embedding = embedding_service
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._db = db
        self._index_lock = asyncio.Lock()

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
