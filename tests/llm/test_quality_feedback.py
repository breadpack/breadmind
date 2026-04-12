"""Tests for SuccessTracker -- record/query, cold start, eviction."""
from __future__ import annotations


from breadmind.llm.quality_feedback import ModelIntentStats, SuccessTracker


class TestModelIntentStats:

    def test_empty_stats_defaults(self):
        stats = ModelIntentStats()
        assert stats.success_count == 0
        assert stats.failure_count == 0
        assert stats.total_count == 0
        assert stats.success_rate == 0.5  # cold start
        assert stats.avg_latency_ms == 0.0
        assert stats.avg_cost == 0.0

    def test_success_rate_calculation(self):
        stats = ModelIntentStats(success_count=8, failure_count=2)
        assert abs(stats.success_rate - 0.8) < 0.001

    def test_avg_latency(self):
        stats = ModelIntentStats(
            success_count=3,
            failure_count=1,
            total_latency_ms=400.0,
        )
        assert abs(stats.avg_latency_ms - 100.0) < 0.001

    def test_avg_cost(self):
        stats = ModelIntentStats(
            success_count=2,
            failure_count=2,
            total_cost=0.04,
        )
        assert abs(stats.avg_cost - 0.01) < 0.0001


class TestSuccessTracker:

    def test_cold_start_returns_neutral(self):
        tracker = SuccessTracker()
        assert tracker.get_success_rate("model", "query") == 0.5

    def test_record_success(self):
        tracker = SuccessTracker()
        tracker.record("model-a", "query", success=True, cost=0.01, latency_ms=100)
        assert tracker.get_success_rate("model-a", "query") == 1.0

    def test_record_failure(self):
        tracker = SuccessTracker()
        tracker.record("model-a", "query", success=False)
        assert tracker.get_success_rate("model-a", "query") == 0.0

    def test_mixed_results(self):
        tracker = SuccessTracker()
        tracker.record("model-a", "query", success=True)
        tracker.record("model-a", "query", success=True)
        tracker.record("model-a", "query", success=False)
        rate = tracker.get_success_rate("model-a", "query")
        assert abs(rate - 2 / 3) < 0.001

    def test_different_intents_tracked_separately(self):
        tracker = SuccessTracker()
        tracker.record("model-a", "query", success=True)
        tracker.record("model-a", "diagnose", success=False)
        assert tracker.get_success_rate("model-a", "query") == 1.0
        assert tracker.get_success_rate("model-a", "diagnose") == 0.0

    def test_different_models_tracked_separately(self):
        tracker = SuccessTracker()
        tracker.record("model-a", "query", success=True)
        tracker.record("model-b", "query", success=False)
        assert tracker.get_success_rate("model-a", "query") == 1.0
        assert tracker.get_success_rate("model-b", "query") == 0.0

    def test_get_stats_returns_full_info(self):
        tracker = SuccessTracker()
        tracker.record("m", "q", success=True, cost=0.01, latency_ms=50)
        tracker.record("m", "q", success=False, cost=0.02, latency_ms=100)
        stats = tracker.get_stats("m", "q")
        assert stats.success_count == 1
        assert stats.failure_count == 1
        assert abs(stats.total_cost - 0.03) < 0.0001
        assert abs(stats.total_latency_ms - 150.0) < 0.001

    def test_get_stats_unknown_returns_empty(self):
        tracker = SuccessTracker()
        stats = tracker.get_stats("unknown", "unknown")
        assert stats.total_count == 0
        assert stats.success_rate == 0.5

    def test_entry_count(self):
        tracker = SuccessTracker()
        tracker.record("a", "1", success=True)
        tracker.record("a", "2", success=True)
        tracker.record("b", "1", success=True)
        assert tracker.entry_count == 3

    def test_lru_eviction(self):
        tracker = SuccessTracker(max_entries=3)
        tracker.record("m1", "i1", success=True)
        tracker.record("m2", "i2", success=True)
        tracker.record("m3", "i3", success=True)
        assert tracker.entry_count == 3

        # Adding a 4th should evict the oldest (m1, i1)
        tracker.record("m4", "i4", success=True)
        assert tracker.entry_count == 3
        assert tracker.get_success_rate("m1", "i1") == 0.5  # evicted -> cold start
        assert tracker.get_success_rate("m4", "i4") == 1.0

    def test_lru_access_refreshes(self):
        tracker = SuccessTracker(max_entries=3)
        tracker.record("m1", "i1", success=True)
        tracker.record("m2", "i2", success=True)
        tracker.record("m3", "i3", success=True)

        # Access m1 to refresh it
        tracker.record("m1", "i1", success=True)

        # Now add m4 -- should evict m2 (oldest untouched)
        tracker.record("m4", "i4", success=True)
        assert tracker.entry_count == 3
        assert tracker.get_success_rate("m2", "i2") == 0.5  # evicted
        assert tracker.get_success_rate("m1", "i1") == 1.0  # still present
