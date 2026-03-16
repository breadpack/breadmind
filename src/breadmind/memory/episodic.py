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
            results = await self._db.search_notes_by_keywords(keywords, limit)
            for note in results:
                self._reinforce(note)
            return results

        scored = []
        for note in self._notes:
            kw_lower = [k.lower() for k in note.keywords]
            score = sum(1 for kw in keywords if kw.lower() in kw_lower)
            if score > 0:
                score *= note.decay_weight
                scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [note for _, note in scored[:limit]]
        for note in results:
            self._reinforce(note)
        return results

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

    def _reinforce(self, note: EpisodicNote):
        """Strengthen a memory on access — like human recall reinforcement.

        Each retrieval boosts decay_weight and updates access tracking.
        More accessed memories resist decay longer.
        """
        note.access_count += 1
        note.last_accessed = datetime.now(timezone.utc)
        # Boost: each access adds 0.1, capped at 1.0
        note.decay_weight = min(1.0, note.decay_weight + 0.1)

    def pin_note(self, note: EpisodicNote):
        """Mark a note as pinned — immune to decay and cleanup."""
        note.pinned = True

    def apply_decay(self):
        """Reduce decay_weight based on time since last access (not creation).

        Human-like: memories decay from last recall, not from creation.
        Frequently accessed memories stay strong. Pinned memories are exempt.
        Formula: weight = base_decay * access_bonus
          - base_decay = 0.95 ^ days_since_last_access
          - access_bonus = min(1.0 + access_count * 0.05, 2.0)
        """
        now = datetime.now(timezone.utc)
        for note in self._notes:
            if note.pinned:
                note.decay_weight = 1.0
                continue

            # Decay from last access (or creation if never accessed)
            ref_time = note.last_accessed or note.created_at
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            days = (now - ref_time).total_seconds() / 86400.0

            base_decay = 0.95 ** days
            # Frequently accessed memories decay slower
            access_bonus = min(1.0 + note.access_count * 0.05, 2.0)
            note.decay_weight = min(1.0, base_decay * access_bonus)

    async def cleanup_low_relevance(self, threshold: float = 0.1) -> int:
        """Remove notes with decay_weight below threshold.

        Pinned notes are never removed. Returns count removed.
        """
        if self._db:
            removed = await self._db.delete_notes_below_weight(threshold)
            self._notes = [
                n for n in self._notes
                if n.pinned or n.decay_weight >= threshold
            ]
            return removed

        before = len(self._notes)
        self._notes = [
            n for n in self._notes
            if n.pinned or n.decay_weight >= threshold
        ]
        return before - len(self._notes)
