import pytest
import asyncio
from breadmind.core.performance import PerformanceTracker, RoleStats, TaskRecord


class TestTaskRecord:
    def test_create_task_record(self):
        record = TaskRecord(
            role="k8s_expert", task_description="Check pod health",
            success=True, duration_ms=1500.0, result_summary="All pods healthy",
        )
        assert record.role == "k8s_expert"
        assert record.success is True
        assert record.timestamp is not None


class TestRoleStats:
    def test_success_rate_no_runs(self):
        stats = RoleStats(role="test")
        assert stats.success_rate == 0.0

    def test_success_rate_with_runs(self):
        stats = RoleStats(role="test", total_runs=10, successes=7, failures=3)
        assert stats.success_rate == 0.7

    def test_avg_duration(self):
        stats = RoleStats(role="test", total_runs=4, total_duration_ms=2000.0)
        assert stats.avg_duration_ms == 500.0


class TestPerformanceTracker:
    @pytest.mark.asyncio
    async def test_record_and_get_stats(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result(role="k8s_expert", task_desc="Check pods", success=True, duration_ms=1200.0, result_summary="OK")
        stats = tracker.get_role_stats("k8s_expert")
        assert stats is not None
        assert stats.total_runs == 1
        assert stats.successes == 1
        assert stats.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("test_role", "task", False, 500.0, "Error")
        stats = tracker.get_role_stats("test_role")
        assert stats.failures == 1
        assert stats.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_get_underperforming_roles(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("good_role", "t1", True, 100.0, "ok")
        await tracker.record_task_result("bad_role", "t2", False, 100.0, "err")
        await tracker.record_task_result("bad_role", "t3", False, 100.0, "err")
        under = tracker.get_underperforming_roles(threshold=0.5)
        assert len(under) == 1
        assert under[0].role == "bad_role"

    @pytest.mark.asyncio
    async def test_record_feedback(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "task", True, 100.0, "ok")
        await tracker.record_feedback("role_a", "good", "Great analysis")
        stats = tracker.get_role_stats("role_a")
        assert len(stats.feedback_history) == 1
        assert stats.feedback_history[0]["rating"] == "good"

    @pytest.mark.asyncio
    async def test_get_all_stats(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t2", True, 200.0, "ok")
        all_stats = tracker.get_all_stats()
        assert "role_a" in all_stats
        assert "role_b" in all_stats

    @pytest.mark.asyncio
    async def test_get_top_roles(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_a", "t2", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t2", False, 100.0, "err")
        top = tracker.get_top_roles(limit=1)
        assert len(top) == 1
        assert top[0].role == "role_a"

    @pytest.mark.asyncio
    async def test_recent_records_cap_at_100(self):
        tracker = PerformanceTracker()
        for i in range(110):
            await tracker.record_task_result("busy_role", f"task_{i}", True, 10.0, "ok")
        stats = tracker.get_role_stats("busy_role")
        assert len(stats.recent_records) == 100
        assert stats.total_runs == 110

    @pytest.mark.asyncio
    async def test_export_import(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        data = tracker.export_stats()
        tracker2 = PerformanceTracker()
        tracker2.import_stats(data)
        stats = tracker2.get_role_stats("role_a")
        assert stats is not None
        assert stats.total_runs == 1

    @pytest.mark.asyncio
    async def test_suggest_improvements(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("bad_role", "t1", False, 100.0, "Connection timeout")
        await tracker.record_task_result("bad_role", "t2", False, 100.0, "Permission denied")
        async def mock_handler(msg, user="", channel=""):
            return "Suggestion: Add retry logic and check permissions."
        result = await tracker.suggest_improvements("bad_role", mock_handler)
        assert "Suggestion" in result or "retry" in result.lower()

    @pytest.mark.asyncio
    async def test_suggest_improvements_no_data(self):
        tracker = PerformanceTracker()
        result = await tracker.suggest_improvements("unknown", None)
        assert "No data" in result

    @pytest.mark.asyncio
    async def test_concurrent_recording(self):
        tracker = PerformanceTracker()
        tasks = [
            tracker.record_task_result(f"role_{i % 3}", f"task_{i}", i % 2 == 0, 10.0, "ok")
            for i in range(30)
        ]
        await asyncio.gather(*tasks)
        total = sum(s.total_runs for s in tracker.get_all_stats().values())
        assert total == 30
