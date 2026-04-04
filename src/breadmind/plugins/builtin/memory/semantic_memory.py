"""v2 SemanticMemory: 지식그래프 메모리."""
from __future__ import annotations

from typing import TYPE_CHECKING

from breadmind.core.protocols import KGTriple

if TYPE_CHECKING:
    from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend


class SemanticMemory:
    """지식그래프. backend이 없으면 인메모리, 있으면 PostgreSQL."""

    def __init__(self, backend: PgMemoryBackend | None = None) -> None:
        self._triples: list[KGTriple] = []
        self._backend = backend

    async def semantic_query(self, entities: list[str]) -> list[KGTriple]:
        if self._backend is not None:
            rows = await self._backend.semantic_query_many(entities)
            return [
                KGTriple(
                    subject=r["subject"],
                    predicate=r["predicate"],
                    object=r["object"],
                    metadata=r.get("metadata", {}),
                )
                for r in rows
            ]
        entities_lower = {e.lower() for e in entities}
        return [
            t for t in self._triples
            if t.subject.lower() in entities_lower or t.object.lower() in entities_lower
        ]

    async def semantic_upsert(self, triples: list[KGTriple]) -> None:
        if self._backend is not None:
            for t in triples:
                await self._backend.semantic_upsert(
                    subject=t.subject,
                    predicate=t.predicate,
                    obj=t.object,
                    confidence=t.metadata.get("confidence", 1.0),
                    metadata=t.metadata,
                )
            return

        for new in triples:
            replaced = False
            for i, existing in enumerate(self._triples):
                if existing.subject == new.subject and existing.predicate == new.predicate:
                    self._triples[i] = new
                    replaced = True
                    break
            if not replaced:
                self._triples.append(new)

    def count(self) -> int:
        """Return triple count (in-memory only). Use count_async() with a backend."""
        return len(self._triples)

    async def count_async(self) -> int:
        """Return triple count, works with both in-memory and backend."""
        if self._backend is not None:
            return await self._backend.semantic_count()
        return len(self._triples)
