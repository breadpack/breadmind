"""v2 SemanticMemory: 지식그래프 메모리."""
from __future__ import annotations
from breadmind.core.protocols import KGTriple


class SemanticMemory:
    """인메모리 지식그래프."""

    def __init__(self) -> None:
        self._triples: list[KGTriple] = []

    async def semantic_query(self, entities: list[str]) -> list[KGTriple]:
        entities_lower = {e.lower() for e in entities}
        return [
            t for t in self._triples
            if t.subject.lower() in entities_lower or t.object.lower() in entities_lower
        ]

    async def semantic_upsert(self, triples: list[KGTriple]) -> None:
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
        return len(self._triples)
