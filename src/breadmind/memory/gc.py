"""Memory garbage collector — periodic cleanup of all memory layers.

Runs as a background asyncio task, performing:
1. WorkingMemory: expire stale sessions
2. EpisodicMemory: apply time decay, remove low-relevance notes
3. SemanticMemory: prune orphaned/stale KG entities
4. In-memory cache: cap episodic notes list to prevent unbounded growth
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MemoryGC:
    """Periodic garbage collector for the 3-layer memory system."""

    def __init__(
        self,
        working_memory,
        episodic_memory,
        semantic_memory,
        interval_seconds: int = 3600,
        decay_threshold: float = 0.1,
        max_cached_notes: int = 500,
        kg_max_age_days: int = 90,
    ):
        self._working = working_memory
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._interval = interval_seconds
        self._decay_threshold = decay_threshold
        self._max_cached_notes = max_cached_notes
        self._kg_max_age_days = kg_max_age_days
        self._task: asyncio.Task | None = None
        self._stats: dict = {"runs": 0, "last_run": None}

    async def start(self):
        """Start the periodic GC loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._gc_loop())
            logger.info(
                "MemoryGC started (interval=%ds, decay_threshold=%.2f, "
                "max_cached_notes=%d, kg_max_age_days=%d)",
                self._interval, self._decay_threshold,
                self._max_cached_notes, self._kg_max_age_days,
            )

    async def stop(self):
        """Stop the periodic GC loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MemoryGC stopped")

    def get_stats(self) -> dict:
        return dict(self._stats)

    async def run_once(self) -> dict:
        """Run a single GC cycle. Returns stats."""
        result = {
            "expired_sessions": 0,
            "decayed_notes": 0,
            "cleaned_notes": 0,
            "trimmed_cache": 0,
            "pruned_entities": 0,
        }

        # 1. WorkingMemory: expire stale sessions
        if self._working:
            try:
                expired = self._working.cleanup_expired()
                result["expired_sessions"] = len(expired)
            except Exception as e:
                logger.warning("WM cleanup failed: %s", e)

        # 2. EpisodicMemory: apply decay and cleanup
        if self._episodic:
            try:
                self._episodic.apply_decay()
                result["decayed_notes"] = len(self._episodic._notes)
            except Exception as e:
                logger.warning("Episodic decay failed: %s", e)

            try:
                removed = await self._episodic.cleanup_low_relevance(
                    threshold=self._decay_threshold,
                )
                result["cleaned_notes"] = removed
            except Exception as e:
                logger.warning("Episodic cleanup failed: %s", e)

            # 2b. Cap in-memory cache to prevent unbounded growth
            try:
                cache_len = len(self._episodic._notes)
                if cache_len > self._max_cached_notes:
                    # Keep most recent notes (by created_at)
                    self._episodic._notes.sort(
                        key=lambda n: n.created_at, reverse=True,
                    )
                    trimmed = cache_len - self._max_cached_notes
                    self._episodic._notes = self._episodic._notes[:self._max_cached_notes]
                    result["trimmed_cache"] = trimmed
            except Exception as e:
                logger.warning("Episodic cache trim failed: %s", e)

        # 3. SemanticMemory: prune old orphaned entities
        if self._semantic:
            try:
                result["pruned_entities"] = await self._prune_kg()
            except Exception as e:
                logger.warning("KG pruning failed: %s", e)

        self._stats["runs"] += 1
        self._stats["last_run"] = datetime.now(timezone.utc).isoformat()
        self._stats["last_result"] = result

        return result

    async def _prune_kg(self) -> int:
        """Remove KG entities that are old and have no relations."""
        now = datetime.now(timezone.utc)
        cutoff_seconds = self._kg_max_age_days * 86400
        pruned = 0

        # Collect all entity IDs that participate in relations
        referenced_ids: set[str] = set()
        for rel in self._semantic._relations:
            referenced_ids.add(rel.source_id)
            referenced_ids.add(rel.target_id)

        # Find orphaned old entities
        to_remove: list[str] = []
        for entity_id, entity in list(self._semantic._entities.items()):
            created = entity.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (now - created).total_seconds()

            if age > cutoff_seconds and entity_id not in referenced_ids:
                to_remove.append(entity_id)

        # Remove from in-memory store
        for entity_id in to_remove:
            self._semantic._entities.pop(entity_id, None)
            pruned += 1

        return pruned

    async def _gc_loop(self):
        """Background loop that runs GC at the configured interval."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                result = await self.run_once()
                # Only log if something was actually cleaned
                if any(v > 0 for k, v in result.items() if k != "decayed_notes"):
                    logger.info(
                        "MemoryGC cycle: sessions=%d, cleaned=%d, "
                        "trimmed=%d, kg_pruned=%d",
                        result["expired_sessions"],
                        result["cleaned_notes"],
                        result["trimmed_cache"],
                        result["pruned_entities"],
                    )
            except Exception as e:
                logger.error("MemoryGC cycle failed: %s", e)
