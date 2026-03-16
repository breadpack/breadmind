"""Tests for MemoryGC."""
import pytest
from datetime import datetime, timezone, timedelta
from breadmind.memory.gc import MemoryGC
from breadmind.memory.working import WorkingMemory
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory
from breadmind.storage.models import KGEntity


@pytest.fixture
def memory_stack():
    wm = WorkingMemory(max_messages_per_session=10, session_timeout_minutes=1)
    em = EpisodicMemory()
    sm = SemanticMemory()
    return wm, em, sm


class TestMemoryGC:
    @pytest.mark.asyncio
    async def test_expired_sessions_cleaned(self, memory_stack):
        wm, em, sm = memory_stack
        # Create a session and force it to be expired
        session = wm.get_or_create_session("test:1", user="u", channel="c")
        session.last_active = datetime.now(timezone.utc) - timedelta(minutes=5)

        gc = MemoryGC(wm, em, sm, interval_seconds=9999)
        result = await gc.run_once()

        assert result["expired_sessions"] == 1
        assert "test:1" not in wm._sessions

    @pytest.mark.asyncio
    async def test_episodic_decay_and_cleanup(self, memory_stack):
        wm, em, sm = memory_stack

        # Add an old note
        note = await em.add_note(
            content="old stuff", keywords=["old"], tags=["test"],
            context_description="test",
        )
        # Force it to be very old (200 days → decay = 0.95^200 ≈ 0.00003)
        note.created_at = datetime.now(timezone.utc) - timedelta(days=200)

        # Add a recent note
        await em.add_note(
            content="new stuff", keywords=["new"], tags=["test"],
            context_description="test",
        )

        gc = MemoryGC(wm, em, sm, interval_seconds=9999, decay_threshold=0.1)
        result = await gc.run_once()

        assert result["cleaned_notes"] == 1  # Old note removed
        assert len(em._notes) == 1  # Only new note remains

    @pytest.mark.asyncio
    async def test_cache_trimming(self, memory_stack):
        wm, em, sm = memory_stack

        # Add 20 notes, max cache = 10
        for i in range(20):
            await em.add_note(
                content=f"note {i}", keywords=[f"kw{i}"], tags=["test"],
                context_description="test",
            )

        gc = MemoryGC(wm, em, sm, interval_seconds=9999, max_cached_notes=10)
        result = await gc.run_once()

        assert result["trimmed_cache"] == 10
        assert len(em._notes) == 10

    @pytest.mark.asyncio
    async def test_kg_prune_orphaned_entities(self, memory_stack):
        wm, em, sm = memory_stack

        # Add an old orphaned entity (no relations)
        old_entity = KGEntity(
            id="ip-1.2.3.4", entity_type="infra_component",
            name="1.2.3.4",
        )
        old_entity.created_at = datetime.now(timezone.utc) - timedelta(days=100)
        await sm.add_entity(old_entity)

        # Add a recent entity (also no relations, but too new to prune)
        new_entity = KGEntity(
            id="ip-5.6.7.8", entity_type="infra_component",
            name="5.6.7.8",
        )
        await sm.add_entity(new_entity)

        gc = MemoryGC(wm, em, sm, interval_seconds=9999, kg_max_age_days=90)
        result = await gc.run_once()

        assert result["pruned_entities"] == 1
        assert "ip-1.2.3.4" not in sm._entities
        assert "ip-5.6.7.8" in sm._entities

    @pytest.mark.asyncio
    async def test_kg_keeps_referenced_entities(self, memory_stack):
        wm, em, sm = memory_stack
        from breadmind.storage.models import KGRelation

        # Add an old entity that HAS relations → should NOT be pruned
        old_entity = KGEntity(
            id="skill:test", entity_type="skill", name="test",
        )
        old_entity.created_at = datetime.now(timezone.utc) - timedelta(days=100)
        await sm.add_entity(old_entity)
        await sm.add_relation(KGRelation(
            source_id="skill:test", target_id="domain:k8s",
            relation_type="related_to",
        ))

        gc = MemoryGC(wm, em, sm, interval_seconds=9999, kg_max_age_days=90)
        result = await gc.run_once()

        assert result["pruned_entities"] == 0
        assert "skill:test" in sm._entities

    @pytest.mark.asyncio
    async def test_stats_tracked(self, memory_stack):
        wm, em, sm = memory_stack
        gc = MemoryGC(wm, em, sm, interval_seconds=9999)

        await gc.run_once()
        stats = gc.get_stats()
        assert stats["runs"] == 1
        assert stats["last_run"] is not None
