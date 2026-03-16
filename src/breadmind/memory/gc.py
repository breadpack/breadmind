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
    """Periodic garbage collector for the 3-layer memory system.

    Lifecycle inspired by human memory:
    1. Decay: memories weaken over time (unless accessed or pinned)
    2. Reinforce: recalled memories get strengthened automatically
    3. Consolidate: similar weak memories merge into generalized knowledge
    4. Prune: truly irrelevant memories are removed
    """

    def __init__(
        self,
        working_memory,
        episodic_memory,
        semantic_memory,
        interval_seconds: int = 3600,
        decay_threshold: float = 0.1,
        max_cached_notes: int = 500,
        kg_max_age_days: int = 90,
        consolidation_enabled: bool = True,
        env_refresh_enabled: bool = True,
        env_refresh_interval: int = 6,  # refresh every N GC cycles (default: 6h)
        db=None,
    ):
        self._working = working_memory
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._interval = interval_seconds
        self._decay_threshold = decay_threshold
        self._max_cached_notes = max_cached_notes
        self._kg_max_age_days = kg_max_age_days
        self._consolidation_enabled = consolidation_enabled
        self._env_refresh_enabled = env_refresh_enabled
        self._env_refresh_interval = env_refresh_interval
        self._db = db
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
            "consolidated_notes": 0,
            "consolidated_entities": 0,
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

        # 4. Consolidation: merge similar weak episodic memories into knowledge
        if self._consolidation_enabled and self._episodic and self._semantic:
            try:
                from breadmind.memory.consolidation import MemoryConsolidator
                consolidator = MemoryConsolidator(
                    episodic_memory=self._episodic,
                    semantic_memory=self._semantic,
                )
                c_result = await consolidator.consolidate()
                result["consolidated_notes"] = c_result["notes_consolidated"]
                result["consolidated_entities"] = c_result["entities_created"]
            except Exception as e:
                logger.warning("Memory consolidation failed: %s", e)

        # 5. Environment refresh — rescan dynamic data (memory, disks, IPs)
        run_number = self._stats.get("runs", 0)
        if (
            self._env_refresh_enabled
            and self._episodic
            and self._semantic
            and run_number > 0  # skip first cycle (initial scan already ran)
            and run_number % self._env_refresh_interval == 0
        ):
            try:
                from breadmind.core.env_scanner import scan_dynamic, store_scan_in_memory
                # Full tool rescan every 24 cycles (24h), lightweight otherwise
                include_tools = (run_number % (self._env_refresh_interval * 4) == 0)
                scan = await scan_dynamic(include_tools=include_tools)
                env_result = await store_scan_in_memory(
                    scan, self._episodic, self._semantic, db=self._db,
                )
                result["env_refreshed"] = True

                # Reconcile: remove KG entries for tools no longer installed
                if include_tools:
                    from breadmind.core.env_scanner import reconcile_tools
                    removed = await reconcile_tools(self._semantic)
                    if removed:
                        result["tools_removed"] = removed
                        logger.info("Removed stale tools from KG: %s", ", ".join(removed))

                extra = " (with tools)" if include_tools else ""
                logger.info(
                    "Environment refreshed%s: memory=%.1fGB free, disks=%d, ips=%d",
                    extra, scan.memory_available_gb, len(scan.disks), len(scan.ip_addresses),
                )
            except Exception as e:
                logger.warning("Environment refresh failed: %s", e)

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
                        "trimmed=%d, kg_pruned=%d, consolidated=%d",
                        result["expired_sessions"],
                        result["cleaned_notes"],
                        result["trimmed_cache"],
                        result["pruned_entities"],
                        result.get("consolidated_notes", 0),
                    )
            except Exception as e:
                logger.error("MemoryGC cycle failed: %s", e)
