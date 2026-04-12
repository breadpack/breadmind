"""Success tracker -- records model performance per intent category.

In-memory tracker with LRU eviction for (model, intent) success/failure stats.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class ModelIntentStats:
    """Aggregated stats for a (model, intent) pair."""
    success_count: int = 0
    failure_count: int = 0
    total_cost: float = 0.0
    total_latency_ms: float = 0.0

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Return success rate, or 0.5 for cold start (no data)."""
        if self.total_count == 0:
            return 0.5
        return self.success_count / self.total_count

    @property
    def avg_latency_ms(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.total_latency_ms / self.total_count

    @property
    def avg_cost(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.total_cost / self.total_count


class SuccessTracker:
    """Track model success/failure rates per intent category with LRU eviction."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._max_entries = max_entries
        # OrderedDict for LRU: key = (model_id, intent_category_value)
        self._stats: OrderedDict[tuple[str, str], ModelIntentStats] = OrderedDict()

    def record(
        self,
        model: str,
        intent: str,
        success: bool,
        cost: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a model invocation result."""
        key = (model, intent)

        if key in self._stats:
            # Move to end (most recently used)
            self._stats.move_to_end(key)
        else:
            # Evict oldest if at capacity
            if len(self._stats) >= self._max_entries:
                self._stats.popitem(last=False)
            self._stats[key] = ModelIntentStats()

        stats = self._stats[key]
        if success:
            stats.success_count += 1
        else:
            stats.failure_count += 1
        stats.total_cost += cost
        stats.total_latency_ms += latency_ms

    def get_success_rate(self, model: str, intent: str) -> float:
        """Return success rate for a (model, intent) pair.

        Returns 0.5 (neutral) for cold start when no data exists.
        """
        key = (model, intent)
        stats = self._stats.get(key)
        if stats is None:
            return 0.5
        return stats.success_rate

    def get_stats(self, model: str, intent: str) -> ModelIntentStats:
        """Return full stats for a (model, intent) pair.

        Returns empty stats if no data exists.
        """
        key = (model, intent)
        return self._stats.get(key, ModelIntentStats())

    @property
    def entry_count(self) -> int:
        """Current number of tracked (model, intent) pairs."""
        return len(self._stats)
