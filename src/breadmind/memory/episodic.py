from datetime import datetime
from breadmind.storage.models import EpisodicNote


class EpisodicMemory:
    """Layer 2: Episodic memory with vector search (pgvector).
    Uses in-memory storage for now; DB integration requires running PostgreSQL."""

    def __init__(self):
        self._notes: list[EpisodicNote] = []
        self._next_id = 1

    async def add_note(
        self,
        content: str,
        keywords: list[str],
        tags: list[str],
        context_description: str,
        embedding: list[float] | None = None,
    ) -> EpisodicNote:
        note = EpisodicNote(
            content=content,
            keywords=keywords,
            tags=tags,
            context_description=context_description,
            embedding=embedding,
            id=self._next_id,
        )
        self._next_id += 1
        self._notes.append(note)
        return note

    async def search_by_keywords(self, keywords: list[str], limit: int = 5) -> list[EpisodicNote]:
        """Simple keyword-based search. Real impl would use pgvector similarity."""
        scored = []
        for note in self._notes:
            score = sum(1 for kw in keywords if kw.lower() in [k.lower() for k in note.keywords])
            if score > 0:
                scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [note for _, note in scored[:limit]]

    async def search_by_tags(self, tags: list[str], limit: int = 5) -> list[EpisodicNote]:
        results = []
        for note in self._notes:
            if any(tag in note.tags for tag in tags):
                results.append(note)
        return results[:limit]

    async def get_note(self, note_id: int) -> EpisodicNote | None:
        for note in self._notes:
            if note.id == note_id:
                return note
        return None

    async def update_note(self, note_id: int, context_description: str | None = None, keywords: list[str] | None = None):
        note = await self.get_note(note_id)
        if note:
            if context_description:
                note.context_description = context_description
            if keywords:
                note.keywords = keywords
            note.updated_at = datetime.utcnow()

    async def link_notes(self, note_id_a: int, note_id_b: int):
        a = await self.get_note(note_id_a)
        b = await self.get_note(note_id_b)
        if a and b:
            if note_id_b not in a.linked_note_ids:
                a.linked_note_ids.append(note_id_b)
            if note_id_a not in b.linked_note_ids:
                b.linked_note_ids.append(note_id_a)

    async def get_all_notes(self) -> list[EpisodicNote]:
        return list(self._notes)

    async def delete_note(self, note_id: int) -> bool:
        for i, note in enumerate(self._notes):
            if note.id == note_id:
                self._notes.pop(i)
                return True
        return False
