from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from breadmind.storage.models import KGEntity, KGRelation

if TYPE_CHECKING:
    from breadmind.storage.database import Database


class SemanticMemory:
    """Layer 3: Knowledge Graph (Apache AGE placeholder).
    Uses in-memory graph by default; pass a Database instance for persistence."""

    def __init__(self, db: Database | None = None):
        self._db = db
        self._entities: dict[str, KGEntity] = {}
        self._relations: list[KGRelation] = []

    async def add_entity(self, entity: KGEntity):
        if self._db:
            await self._db.save_entity(entity)
        self._entities[entity.id] = entity

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        if self._db:
            return await self._db.get_entity(entity_id)
        return self._entities.get(entity_id)

    async def find_entities(
        self,
        entity_type: str | None = None,
        name_contains: str | None = None,
    ) -> list[KGEntity]:
        if self._db:
            return await self._db.search_entities(
                name_contains=name_contains, entity_type=entity_type
            )

        results = []
        for e in self._entities.values():
            if entity_type and e.entity_type != entity_type:
                continue
            if name_contains and name_contains.lower() not in e.name.lower():
                continue
            results.append(e)
        return results

    async def add_relation(self, relation: KGRelation):
        if self._db:
            rel_id = await self._db.save_relation(relation)
            relation.id = rel_id
        self._relations.append(relation)

    async def get_relations(
        self, entity_id: str, direction: str = "both"
    ) -> list[KGRelation]:
        results = []
        for r in self._relations:
            if direction in ("out", "both") and r.source_id == entity_id:
                results.append(r)
            if direction in ("in", "both") and r.target_id == entity_id:
                results.append(r)
        return results

    async def get_neighbors(self, entity_id: str) -> list[KGEntity]:
        if self._db:
            return await self._db.get_neighbors(entity_id)

        neighbor_ids = set()
        for r in self._relations:
            if r.source_id == entity_id:
                neighbor_ids.add(r.target_id)
            elif r.target_id == entity_id:
                neighbor_ids.add(r.source_id)
        return [
            self._entities[nid] for nid in neighbor_ids if nid in self._entities
        ]

    async def update_weight(self, entity_id: str, delta: float = 0.1):
        entity = self._entities.get(entity_id)
        if entity:
            entity.weight += delta

    async def get_context_for_query(
        self, keywords: list[str], limit: int = 5
    ) -> list[KGEntity]:
        """Find entities related to keywords, sorted by weight."""
        if self._db:
            # For DB mode, search by each keyword and deduplicate
            seen: dict[str, KGEntity] = {}
            for kw in keywords:
                entities = await self._db.search_entities(name_contains=kw, limit=limit)
                for e in entities:
                    if e.id not in seen:
                        seen[e.id] = e
            results = sorted(seen.values(), key=lambda e: e.weight, reverse=True)
            return results[:limit]

        scored = []
        for e in self._entities.values():
            score = 0
            for kw in keywords:
                if kw.lower() in e.name.lower() or kw.lower() in str(
                    e.properties
                ).lower():
                    score += e.weight
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]
