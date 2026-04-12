"""Tests for usage_analytics module."""

from __future__ import annotations

import time

import pytest

from breadmind.tools.usage_analytics import (
    AnalyticsEvent,
    UsageAnalytics,
)


@pytest.fixture
def analytics() -> UsageAnalytics:
    return UsageAnalytics()


# -- track --


def test_track_adds_event(analytics: UsageAnalytics):
    analytics.track("tool_a", "tool")
    assert len(analytics._events) == 1
    assert analytics._events[0].component_name == "tool_a"


def test_track_respects_max_events():
    a = UsageAnalytics(max_events=5)
    for i in range(10):
        a.track(f"t{i}", "tool")
    assert len(a._events) == 5
    # Should keep the latest events
    assert a._events[0].component_name == "t5"


def test_track_with_metadata(analytics: UsageAnalytics):
    analytics.track("t", "tool", metadata={"user": "admin"})
    assert analytics._events[0].metadata == {"user": "admin"}


# -- generate_report --


def test_generate_report_basic(analytics: UsageAnalytics):
    analytics.track("a", "tool", duration_ms=100)
    analytics.track("a", "tool", duration_ms=200)
    analytics.track("b", "skill", success=False)
    report = analytics.generate_report(hours=1)
    assert report.total_events == 3
    assert report.unique_components == 2
    assert report.most_used[0] == ("a", 2)
    assert report.most_errors[0] == ("b", 1)
    assert report.by_type["tool"] == 2
    assert report.by_type["skill"] == 1


def test_generate_report_slowest(analytics: UsageAnalytics):
    analytics.track("slow", "tool", duration_ms=500)
    analytics.track("fast", "tool", duration_ms=10)
    report = analytics.generate_report(hours=1)
    assert report.slowest[0][0] == "slow"
    assert report.slowest[0][1] == 500.0


def test_generate_report_respects_time_window(analytics: UsageAnalytics):
    old_event = AnalyticsEvent(
        component_name="old",
        component_type="tool",
        action="invoke",
        timestamp=time.time() - 7200,  # 2 hours ago
    )
    analytics._events.append(old_event)
    analytics.track("new", "tool")
    report = analytics.generate_report(hours=1)
    assert report.total_events == 1
    assert report.most_used[0][0] == "new"


# -- get_component_stats --


def test_get_component_stats(analytics: UsageAnalytics):
    analytics.track("t", "tool", duration_ms=100, success=True)
    analytics.track("t", "tool", duration_ms=300, success=False)
    stats = analytics.get_component_stats("t")
    assert stats["total_invocations"] == 2
    assert stats["successes"] == 1
    assert stats["failures"] == 1
    assert stats["error_rate"] == 0.5
    assert stats["avg_duration_ms"] == 200.0


def test_get_component_stats_unknown(analytics: UsageAnalytics):
    assert analytics.get_component_stats("nope") == {}


# -- get_unused_components --


def test_get_unused_components(analytics: UsageAnalytics):
    analytics.track("used_tool", "tool")
    registered = ["used_tool", "unused_tool", "another_unused"]
    unused = analytics.get_unused_components(registered, hours=1)
    assert "unused_tool" in unused
    assert "another_unused" in unused
    assert "used_tool" not in unused


# -- get_error_prone --


def test_get_error_prone(analytics: UsageAnalytics):
    for _ in range(8):
        analytics.track("flaky", "tool", success=True)
    for _ in range(4):
        analytics.track("flaky", "tool", success=False)
    # 4/12 = 0.333 error rate
    result = analytics.get_error_prone(min_error_rate=0.2, min_invocations=5)
    assert len(result) == 1
    name, rate, total = result[0]
    assert name == "flaky"
    assert total == 12
    assert abs(rate - 4 / 12) < 0.01


def test_get_error_prone_filters_low_invocations(analytics: UsageAnalytics):
    analytics.track("rare", "tool", success=False)
    analytics.track("rare", "tool", success=False)
    result = analytics.get_error_prone(min_error_rate=0.1, min_invocations=5)
    assert len(result) == 0


# -- get_performance_outliers --


def test_get_performance_outliers(analytics: UsageAnalytics):
    for _ in range(20):
        analytics.track("fast", "tool", duration_ms=10)
    analytics.track("slow", "tool", duration_ms=5000)
    outliers = analytics.get_performance_outliers(percentile=90)
    names = [name for name, _ in outliers]
    assert "slow" in names


# -- get_hourly_pattern --


def test_get_hourly_pattern(analytics: UsageAnalytics):
    analytics.track("t", "tool")
    pattern = analytics.get_hourly_pattern()
    assert sum(pattern.values()) == 1


# -- get_daily_trend --


def test_get_daily_trend(analytics: UsageAnalytics):
    analytics.track("t", "tool")
    trend = analytics.get_daily_trend(days=1)
    assert len(trend) >= 1
    assert trend[0][1] >= 1


# -- export_events --


def test_export_events_all(analytics: UsageAnalytics):
    analytics.track("a", "tool")
    analytics.track("b", "skill")
    exported = analytics.export_events()
    assert len(exported) == 2
    assert exported[0]["component_name"] == "a"


def test_export_events_filtered_by_hours(analytics: UsageAnalytics):
    old = AnalyticsEvent(
        component_name="old",
        component_type="tool",
        action="invoke",
        timestamp=time.time() - 7200,
    )
    analytics._events.append(old)
    analytics.track("new", "tool")
    exported = analytics.export_events(hours=1)
    assert len(exported) == 1
    assert exported[0]["component_name"] == "new"


# -- clear --


def test_clear(analytics: UsageAnalytics):
    analytics.track("t", "tool")
    analytics.clear()
    assert len(analytics._events) == 0
