"""AutoDream Memory Consolidation — background sub-agent for memory optimization.

Runs between sessions to consolidate memory: pruning stale entries,
merging related information, and refreshing outdated content.
Analogous to REM sleep for the agent's memory system.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DreamAction(str, Enum):
    PRUNE = "prune"
    MERGE = "merge"
    REFRESH = "refresh"
    KEEP = "keep"


@dataclass
class DreamResult:
    action: DreamAction
    source_entries: list[str]  # Entry IDs affected
    new_content: str | None = None  # For merge/refresh
    reason: str = ""


@dataclass
class ConsolidationReport:
    pruned: int = 0
    merged: int = 0
    refreshed: int = 0
    kept: int = 0
    duration_ms: float = 0
    details: list[DreamResult] = field(default_factory=list)


@dataclass
class MemoryEntry:
    id: str
    content: str
    category: str = ""  # "decision", "finding", "preference", etc.
    created_at: float = 0
    last_accessed: float = 0
    access_count: int = 0
    source_file: Path | None = None


class AutoDreamer:
    """Background memory consolidation agent.

    Runs between sessions to optimize memory:
    1. Prune stale entries (not accessed in N days, outdated info)
    2. Merge related entries (similar topics, duplicate info)
    3. Refresh entries (update with current project state)

    Uses heuristic scoring — no LLM needed for basic consolidation.
    """

    def __init__(
        self,
        stale_days: int = 30,
        similarity_threshold: float = 0.7,
        max_entries: int = 500,
    ):
        self._stale_days = stale_days
        self._similarity_threshold = similarity_threshold
        self._max_entries = max_entries

    def consolidate(self, entries: list[MemoryEntry]) -> ConsolidationReport:
        """Run full consolidation cycle on memory entries."""
        start = time.monotonic()

        stale_results = self.identify_stale(entries)
        stale_ids: set[str] = set()
        for r in stale_results:
            stale_ids.update(r.source_entries)

        remaining = [e for e in entries if e.id not in stale_ids]
        merge_results = self.identify_duplicates(remaining)

        all_results = stale_results + merge_results

        # Everything not touched by prune/merge is kept
        affected_ids: set[str] = set()
        for r in all_results:
            affected_ids.update(r.source_entries)

        for entry in entries:
            if entry.id not in affected_ids:
                all_results.append(
                    DreamResult(
                        action=DreamAction.KEEP,
                        source_entries=[entry.id],
                        reason="No consolidation needed",
                    )
                )

        elapsed_ms = (time.monotonic() - start) * 1000

        report = ConsolidationReport(
            pruned=sum(1 for r in all_results if r.action == DreamAction.PRUNE),
            merged=sum(1 for r in all_results if r.action == DreamAction.MERGE),
            refreshed=sum(1 for r in all_results if r.action == DreamAction.REFRESH),
            kept=sum(1 for r in all_results if r.action == DreamAction.KEEP),
            duration_ms=elapsed_ms,
            details=all_results,
        )
        return report

    def identify_stale(
        self, entries: list[MemoryEntry], now: float | None = None,
    ) -> list[DreamResult]:
        """Find entries that haven't been accessed recently."""
        if now is None:
            now = time.time()

        stale_threshold = now - (self._stale_days * 86400)
        results: list[DreamResult] = []

        for entry in entries:
            last_touch = max(entry.last_accessed, entry.created_at)
            if last_touch < stale_threshold and entry.access_count < 3:
                results.append(
                    DreamResult(
                        action=DreamAction.PRUNE,
                        source_entries=[entry.id],
                        reason=(
                            f"Not accessed in {self._stale_days}+ days "
                            f"(access_count={entry.access_count})"
                        ),
                    )
                )

        return results

    def identify_duplicates(
        self, entries: list[MemoryEntry],
    ) -> list[DreamResult]:
        """Find entries with similar content that can be merged.

        Uses simple text similarity (Jaccard on word sets).
        """
        results: list[DreamResult] = []
        merged_ids: set[str] = set()
        word_sets = {e.id: self._word_set(e.content) for e in entries}
        entry_map = {e.id: e for e in entries}

        for i, a in enumerate(entries):
            if a.id in merged_ids:
                continue
            for b in entries[i + 1 :]:
                if b.id in merged_ids:
                    continue
                sim = self._jaccard_similarity(word_sets[a.id], word_sets[b.id])
                if sim >= self._similarity_threshold:
                    # Keep the one with higher access count; merge content
                    primary = a if a.access_count >= b.access_count else b
                    secondary = b if primary is a else a
                    merged_content = self._merge_content(primary, secondary)
                    results.append(
                        DreamResult(
                            action=DreamAction.MERGE,
                            source_entries=[a.id, b.id],
                            new_content=merged_content,
                            reason=f"Similarity {sim:.2f} >= {self._similarity_threshold}",
                        )
                    )
                    merged_ids.add(a.id)
                    merged_ids.add(b.id)
                    break  # a is consumed, move on

        return results

    def _word_set(self, text: str) -> set[str]:
        """Extract normalized word set for comparison."""
        words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        # Filter out very short words that add noise
        return {w for w in words if len(w) > 2}

    def _jaccard_similarity(self, a: set, b: set) -> float:
        """Compute Jaccard similarity between two sets."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union

    def _merge_content(
        self, primary: MemoryEntry, secondary: MemoryEntry,
    ) -> str:
        """Merge two entries, keeping primary content and appending unique info."""
        primary_words = self._word_set(primary.content)
        secondary_words = self._word_set(secondary.content)
        unique_in_secondary = secondary_words - primary_words

        if not unique_in_secondary:
            return primary.content

        return f"{primary.content}\n(merged: {secondary.content})"

    def apply_results(
        self,
        entries: list[MemoryEntry],
        results: list[DreamResult],
    ) -> list[MemoryEntry]:
        """Apply dream results to produce consolidated entry list."""
        entry_map = {e.id: e for e in entries}
        pruned_ids: set[str] = set()
        merged_ids: set[str] = set()
        new_entries: list[MemoryEntry] = []

        for result in results:
            if result.action == DreamAction.PRUNE:
                pruned_ids.update(result.source_entries)
            elif result.action == DreamAction.MERGE:
                merged_ids.update(result.source_entries)
                # Create merged entry from the first source
                if result.source_entries:
                    base_id = result.source_entries[0]
                    base = entry_map.get(base_id)
                    if base is not None:
                        merged = MemoryEntry(
                            id=base.id,
                            content=result.new_content or base.content,
                            category=base.category,
                            created_at=base.created_at,
                            last_accessed=time.time(),
                            access_count=sum(
                                entry_map[eid].access_count
                                for eid in result.source_entries
                                if eid in entry_map
                            ),
                            source_file=base.source_file,
                        )
                        new_entries.append(merged)

        # Keep untouched entries
        removed = pruned_ids | merged_ids
        kept = [e for e in entries if e.id not in removed]
        return kept + new_entries

    def should_run(
        self, last_run: float | None, min_interval_hours: int = 24,
    ) -> bool:
        """Check if enough time has passed since last consolidation."""
        if last_run is None:
            return True
        elapsed_hours = (time.time() - last_run) / 3600
        return elapsed_hours >= min_interval_hours
