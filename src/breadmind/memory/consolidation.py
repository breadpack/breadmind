"""Memory consolidation — merge similar episodic memories into semantic knowledge.

Mimics human sleep consolidation: clusters related episodic notes,
summarizes them into generalized knowledge, and stores in the KG.
Old individual episodes are then replaced by the consolidated summary.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """Periodically consolidates episodic memories into semantic knowledge."""

    def __init__(
        self,
        episodic_memory,
        semantic_memory,
        min_cluster_size: int = 3,
        keyword_overlap_threshold: float = 0.3,
    ):
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._min_cluster_size = min_cluster_size
        self._kw_threshold = keyword_overlap_threshold

    async def consolidate(self) -> dict:
        """Run one consolidation cycle.

        1. Cluster episodic notes by keyword similarity
        2. For clusters >= min_cluster_size, create a consolidated summary
        3. Store summary as a new pinned episodic note + KG entity
        4. Remove individual old notes from the cluster

        Returns stats about what was consolidated.
        """
        notes = await self._episodic.get_all_notes()
        if len(notes) < self._min_cluster_size:
            return {"clusters_found": 0, "notes_consolidated": 0, "entities_created": 0}

        # Only consolidate non-pinned, older notes
        eligible = [
            n for n in notes
            if not n.pinned and n.decay_weight < 0.8
        ]
        if len(eligible) < self._min_cluster_size:
            return {"clusters_found": 0, "notes_consolidated": 0, "entities_created": 0}

        clusters = self._cluster_by_keywords(eligible)
        consolidated_count = 0
        entities_created = 0

        for cluster_keywords, cluster_notes in clusters.items():
            if len(cluster_notes) < self._min_cluster_size:
                continue

            # Build consolidated content
            summary = self._build_summary(cluster_keywords, cluster_notes)

            # Create a pinned summary note
            merged_keywords = list(set(
                kw for note in cluster_notes for kw in note.keywords
            ))[:20]

            summary_note = await self._episodic.add_note(
                content=summary,
                keywords=merged_keywords,
                tags=["consolidated", f"cluster:{cluster_keywords}"],
                context_description=f"Consolidated from {len(cluster_notes)} episodes",
            )
            self._episodic.pin_note(summary_note)

            # Create KG entity for the consolidated knowledge
            entity_id = f"consolidated:{cluster_keywords}"
            entity = KGEntity(
                id=entity_id,
                entity_type="consolidated_knowledge",
                name=cluster_keywords,
                properties={
                    "source_count": len(cluster_notes),
                    "summary": summary[:500],
                    "keywords": merged_keywords[:10],
                },
            )
            await self._semantic.add_entity(entity)
            entities_created += 1

            # Link to related domain entities
            for kw in merged_keywords[:5]:
                domain_id = f"domain:{kw}"
                existing = await self._semantic.get_entity(domain_id)
                if existing:
                    await self._semantic.add_relation(KGRelation(
                        source_id=entity_id,
                        target_id=domain_id,
                        relation_type="consolidates",
                    ))

            # Remove old individual notes
            for note in cluster_notes:
                await self._episodic.delete_note(note.id)
                consolidated_count += 1

            logger.info(
                "Consolidated %d notes into '%s'",
                len(cluster_notes), cluster_keywords,
            )

        return {
            "clusters_found": len([c for c in clusters.values() if len(c) >= self._min_cluster_size]),
            "notes_consolidated": consolidated_count,
            "entities_created": entities_created,
        }

    def _cluster_by_keywords(
        self, notes: list[EpisodicNote],
    ) -> dict[str, list[EpisodicNote]]:
        """Group notes by keyword overlap using greedy clustering."""
        clusters: dict[str, list[EpisodicNote]] = defaultdict(list)
        assigned: set[int] = set()

        # Sort by decay_weight ascending (oldest/weakest first)
        sorted_notes = sorted(notes, key=lambda n: n.decay_weight)

        for i, note_a in enumerate(sorted_notes):
            if note_a.id in assigned:
                continue

            kw_a = set(k.lower() for k in note_a.keywords)
            if not kw_a:
                continue

            # Find the dominant keyword for cluster name
            cluster_key = note_a.keywords[0].lower() if note_a.keywords else str(note_a.id)
            cluster = [note_a]
            assigned.add(note_a.id)

            for j, note_b in enumerate(sorted_notes):
                if i == j or note_b.id in assigned:
                    continue
                kw_b = set(k.lower() for k in note_b.keywords)
                if not kw_b:
                    continue

                overlap = len(kw_a & kw_b) / max(len(kw_a | kw_b), 1)
                if overlap >= self._kw_threshold:
                    cluster.append(note_b)
                    assigned.add(note_b.id)
                    kw_a = kw_a | kw_b  # Expand cluster keywords

            clusters[cluster_key] = cluster

        return dict(clusters)

    def _build_summary(
        self, cluster_name: str, notes: list[EpisodicNote],
    ) -> str:
        """Build a consolidated summary from clustered notes.

        Uses extractive summarization (no LLM) — picks key sentences
        and deduplicates.
        """
        # Collect unique content lines
        seen: set[str] = set()
        lines: list[str] = []
        for note in notes:
            # Normalize and deduplicate
            normalized = note.content.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                lines.append(normalized)

        # Build summary
        header = f"[Consolidated knowledge: {cluster_name}] ({len(notes)} episodes merged)"
        # Limit to 10 most representative lines
        body = "\n".join(f"- {line}" for line in lines[:10])
        if len(lines) > 10:
            body += f"\n  ... and {len(lines) - 10} more entries"

        return f"{header}\n{body}"
