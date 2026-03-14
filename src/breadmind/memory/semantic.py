from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class KGEntity:
    id: str
    entity_type: str     # "user_preference" | "infra_component" | "pattern"
    name: str
    properties: dict = field(default_factory=dict)
    weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class KGRelation:
    source_id: str
    target_id: str
    relation_type: str   # "prefers" | "manages" | "depends_on" | "related_to"
    weight: float = 1.0
    properties: dict = field(default_factory=dict)


class SemanticMemory:
    """Layer 3: Knowledge Graph (Apache AGE placeholder).
    Uses in-memory graph for now; DB integration requires running PostgreSQL + AGE."""

    def __init__(self):
        self._entities: dict[str, KGEntity] = {}
        self._relations: list[KGRelation] = []

    async def add_entity(self, entity: KGEntity):
        self._entities[entity.id] = entity

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        return self._entities.get(entity_id)

    async def find_entities(self, entity_type: str | None = None, name_contains: str | None = None) -> list[KGEntity]:
        results = []
        for e in self._entities.values():
            if entity_type and e.entity_type != entity_type:
                continue
            if name_contains and name_contains.lower() not in e.name.lower():
                continue
            results.append(e)
        return results

    async def add_relation(self, relation: KGRelation):
        self._relations.append(relation)

    async def get_relations(self, entity_id: str, direction: str = "both") -> list[KGRelation]:
        results = []
        for r in self._relations:
            if direction in ("out", "both") and r.source_id == entity_id:
                results.append(r)
            if direction in ("in", "both") and r.target_id == entity_id:
                results.append(r)
        return results

    async def get_neighbors(self, entity_id: str) -> list[KGEntity]:
        neighbor_ids = set()
        for r in self._relations:
            if r.source_id == entity_id:
                neighbor_ids.add(r.target_id)
            elif r.target_id == entity_id:
                neighbor_ids.add(r.source_id)
        return [self._entities[nid] for nid in neighbor_ids if nid in self._entities]

    async def update_weight(self, entity_id: str, delta: float = 0.1):
        entity = self._entities.get(entity_id)
        if entity:
            entity.weight += delta

    async def get_context_for_query(self, keywords: list[str], limit: int = 5) -> list[KGEntity]:
        """Find entities related to keywords, sorted by weight."""
        scored = []
        for e in self._entities.values():
            score = 0
            for kw in keywords:
                if kw.lower() in e.name.lower() or kw.lower() in str(e.properties).lower():
                    score += e.weight
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]
