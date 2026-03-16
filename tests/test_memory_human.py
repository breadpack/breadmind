"""Tests for human-like memory behaviors: reinforcement, pinning, consolidation."""
import pytest
from datetime import datetime, timezone, timedelta
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory
from breadmind.memory.consolidation import MemoryConsolidator


class TestRecallReinforcement:
    @pytest.mark.asyncio
    async def test_search_reinforces_memory(self):
        em = EpisodicMemory()
        note = await em.add_note(
            content="Proxmox is at 10.0.0.50",
            keywords=["proxmox", "10.0.0.50"],
            tags=["fact"], context_description="test",
        )
        # Force decay
        note.decay_weight = 0.3
        assert note.access_count == 0

        # Search should reinforce
        results = await em.search_by_keywords(["proxmox"])
        assert len(results) == 1
        assert results[0].access_count == 1
        assert results[0].decay_weight == 0.4  # 0.3 + 0.1

    @pytest.mark.asyncio
    async def test_multiple_accesses_strengthen(self):
        em = EpisodicMemory()
        note = await em.add_note(
            content="important fact",
            keywords=["important"],
            tags=["fact"], context_description="test",
        )
        note.decay_weight = 0.5

        for _ in range(5):
            await em.search_by_keywords(["important"])

        assert note.access_count == 5
        assert note.decay_weight >= 0.99  # effectively capped at 1.0

    @pytest.mark.asyncio
    async def test_decay_uses_last_access_not_creation(self):
        em = EpisodicMemory()
        note = await em.add_note(
            content="old but accessed",
            keywords=["test"],
            tags=["fact"], context_description="test",
        )
        # Created 100 days ago
        note.created_at = datetime.now(timezone.utc) - timedelta(days=100)
        # But accessed today
        note.last_accessed = datetime.now(timezone.utc)
        note.access_count = 5

        em.apply_decay()

        # Should still be high because last access is recent
        assert note.decay_weight > 0.9


class TestPinning:
    @pytest.mark.asyncio
    async def test_pinned_notes_immune_to_decay(self):
        em = EpisodicMemory()
        note = await em.add_note(
            content="pinned memory",
            keywords=["server"],
            tags=["fact"], context_description="test",
        )
        em.pin_note(note)
        note.created_at = datetime.now(timezone.utc) - timedelta(days=1000)

        em.apply_decay()
        assert note.decay_weight == 1.0

    @pytest.mark.asyncio
    async def test_pinned_notes_immune_to_cleanup(self):
        em = EpisodicMemory()
        note = await em.add_note(
            content="pinned memory",
            keywords=["server"],
            tags=["fact"], context_description="test",
        )
        em.pin_note(note)
        note.decay_weight = 0.001  # Force very low weight

        removed = await em.cleanup_low_relevance(threshold=0.1)
        assert removed == 0
        assert len(em._notes) == 1


class TestConsolidation:
    @pytest.mark.asyncio
    async def test_similar_notes_consolidated(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        # Create 3 similar notes about "proxmox"
        for i in range(3):
            note = await em.add_note(
                content=f"Proxmox event {i}: CPU high",
                keywords=["proxmox", "cpu", "high"],
                tags=["auto-promoted"], context_description="test",
            )
            note.decay_weight = 0.5  # Weakened enough for consolidation

        consolidator = MemoryConsolidator(em, sm, min_cluster_size=3)
        result = await consolidator.consolidate()

        assert result["clusters_found"] == 1
        assert result["notes_consolidated"] == 3
        assert result["entities_created"] == 1

        # Individual notes replaced by consolidated summary
        remaining = [n for n in em._notes if not n.pinned]
        assert len(remaining) == 0  # Old notes removed
        pinned = [n for n in em._notes if n.pinned]
        assert len(pinned) == 1  # Consolidated summary is pinned
        assert "Consolidated" in pinned[0].content

    @pytest.mark.asyncio
    async def test_strong_memories_not_consolidated(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        # Create 3 similar but STRONG notes (decay_weight > 0.8)
        for i in range(3):
            note = await em.add_note(
                content=f"Recent event {i}",
                keywords=["recent", "event"],
                tags=["test"], context_description="test",
            )
            note.decay_weight = 0.9  # Too strong for consolidation

        consolidator = MemoryConsolidator(em, sm, min_cluster_size=3)
        result = await consolidator.consolidate()

        assert result["notes_consolidated"] == 0
        assert len(em._notes) == 3  # All preserved

    @pytest.mark.asyncio
    async def test_dissimilar_notes_not_clustered(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        # Create 3 notes with completely different keywords
        topics = [
            (["proxmox", "vm"], "Proxmox VM issue"),
            (["kubernetes", "pod"], "K8s pod crash"),
            (["network", "firewall"], "Firewall blocked"),
        ]
        for kws, content in topics:
            note = await em.add_note(
                content=content, keywords=kws,
                tags=["test"], context_description="test",
            )
            note.decay_weight = 0.5

        consolidator = MemoryConsolidator(em, sm, min_cluster_size=3)
        result = await consolidator.consolidate()

        assert result["notes_consolidated"] == 0  # Too dissimilar
