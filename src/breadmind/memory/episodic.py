from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from breadmind.storage.models import EpisodicNote

if TYPE_CHECKING:
    from breadmind.storage.database import Database


class EpisodicMemory:
    """Layer 2: Episodic memory with vector search (pgvector).
    Uses in-memory storage by default; pass a Database instance for persistence."""

    def __init__(self, db: Database | None = None):
        self._db = db
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

        if self._db:
            note_id = await self._db.save_note(note)
            note.id = note_id
        else:
            self._next_id += 1

        self._notes.append(note)
        return note

    async def search_by_keywords(
        self, keywords: list[str], limit: int = 5
    ) -> list[EpisodicNote]:
        if self._db:
            return await self._db.search_notes_by_keywords(keywords, limit)

        scored = []
        for note in self._notes:
            kw_lower = [k.lower() for k in note.keywords]
            score = sum(1 for kw in keywords if kw.lower() in kw_lower)
            if score > 0:
                score *= note.decay_weight
                scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [note for _, note in scored[:limit]]

    async def search_by_tags(
        self, tags: list[str], limit: int = 5
    ) -> list[EpisodicNote]:
        if self._db:
            return await self._db.search_notes_by_tags(tags, limit)

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

    async def update_note(
        self,
        note_id: int,
        context_description: str | None = None,
        keywords: list[str] | None = None,
    ):
        note = await self.get_note(note_id)
        if note:
            if context_description:
                note.context_description = context_description
            if keywords:
                note.keywords = keywords
            note.updated_at = datetime.now(timezone.utc)

    async def link_notes(self, note_id_a: int, note_id_b: int):
        if self._db:
            await self._db.link_notes(note_id_a, note_id_b)

        a = await self.get_note(note_id_a)
        b = await self.get_note(note_id_b)
        if a and b:
            if note_id_b not in a.linked_note_ids:
                a.linked_note_ids.append(note_id_b)
            if note_id_a not in b.linked_note_ids:
                b.linked_note_ids.append(note_id_a)

    async def get_all_notes(self) -> list[EpisodicNote]:
        if self._db:
            return await self._db.get_all_notes()
        return list(self._notes)

    async def delete_note(self, note_id: int) -> bool:
        if self._db:
            await self._db.delete_note(note_id)

        for i, note in enumerate(self._notes):
            if note.id == note_id:
                self._notes.pop(i)
                return True
        return False

    def apply_decay(self):
        """Reduce decay_weight of all notes based on age.
        Formula: weight *= 0.95 ** days_since_creation
        """
        now = datetime.now(timezone.utc)
        for note in self._notes:
            created = note.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days = (now - created).total_seconds() / 86400.0
            note.decay_weight = 0.95 ** days

    async def cleanup_low_relevance(self, threshold: float = 0.1) -> int:
        """Remove notes with decay_weight below threshold. Returns count removed."""
        if self._db:
            removed = await self._db.delete_notes_below_weight(threshold)
            self._notes = [n for n in self._notes if n.decay_weight >= threshold]
            return removed

        before = len(self._notes)
        self._notes = [n for n in self._notes if n.decay_weight >= threshold]
        return before - len(self._notes)
