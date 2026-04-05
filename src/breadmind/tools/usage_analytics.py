"""Analytics and reporting for tool/skill/MCP usage patterns."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AnalyticsEvent:
    component_name: str
    component_type: str  # "tool", "skill", "mcp_server"
    action: str  # "invoke", "install", "uninstall", "error"
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0
    success: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class UsageReport:
    period_start: float
    period_end: float
    total_events: int = 0
    unique_components: int = 0

    # Top lists
    most_used: list[tuple[str, int]] = field(default_factory=list)
    least_used: list[tuple[str, int]] = field(default_factory=list)
    most_errors: list[tuple[str, int]] = field(default_factory=list)
    slowest: list[tuple[str, float]] = field(default_factory=list)

    # Type breakdown
    by_type: dict[str, int] = field(default_factory=dict)

    # Trends
    hourly_distribution: dict[int, int] = field(default_factory=dict)


class UsageAnalytics:
    """Tracks and analyzes tool/skill/MCP usage patterns.

    Provides:
    - Usage frequency tracking
    - Performance metrics (response times)
    - Error rate monitoring
    - Time-based usage patterns (hourly/daily)
    - Component lifecycle tracking (installs/uninstalls)
    - Reports for optimization insights
    """

    def __init__(self, max_events: int = 10000) -> None:
        self._events: list[AnalyticsEvent] = []
        self._max_events = max_events

    def track(
        self,
        component_name: str,
        component_type: str,
        action: str = "invoke",
        duration_ms: float = 0,
        success: bool = True,
        metadata: dict | None = None,
    ) -> None:
        """Track a usage event."""
        event = AnalyticsEvent(
            component_name=component_name,
            component_type=component_type,
            action=action,
            duration_ms=duration_ms,
            success=success,
            metadata=metadata or {},
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

    def generate_report(self, hours: float = 24, limit: int = 10) -> UsageReport:
        """Generate a usage report for the specified time period."""
        now = time.time()
        cutoff = now - hours * 3600
        filtered = [e for e in self._events if e.timestamp >= cutoff]

        report = UsageReport(period_start=cutoff, period_end=now)
        report.total_events = len(filtered)

        # Count by component
        usage_counter: Counter[str] = Counter()
        error_counter: Counter[str] = Counter()
        duration_totals: dict[str, list[float]] = defaultdict(list)
        type_counter: Counter[str] = Counter()

        for ev in filtered:
            usage_counter[ev.component_name] += 1
            type_counter[ev.component_type] += 1
            if ev.duration_ms > 0:
                duration_totals[ev.component_name].append(ev.duration_ms)
            if not ev.success:
                error_counter[ev.component_name] += 1

        report.unique_components = len(usage_counter)
        report.most_used = usage_counter.most_common(limit)
        report.least_used = usage_counter.most_common()[:-limit - 1:-1] if usage_counter else []
        report.most_errors = error_counter.most_common(limit)

        # Slowest by average duration
        avg_durations = {
            name: sum(durs) / len(durs)
            for name, durs in duration_totals.items()
        }
        report.slowest = sorted(
            avg_durations.items(), key=lambda x: x[1], reverse=True
        )[:limit]

        report.by_type = dict(type_counter)

        # Hourly distribution
        hourly: Counter[int] = Counter()
        for ev in filtered:
            hour = datetime.fromtimestamp(ev.timestamp, tz=timezone.utc).hour
            hourly[hour] += 1
        report.hourly_distribution = dict(hourly)

        return report

    def get_component_stats(self, name: str) -> dict:
        """Get detailed stats for a specific component."""
        events = [e for e in self._events if e.component_name == name]
        if not events:
            return {}

        total = len(events)
        successes = sum(1 for e in events if e.success)
        failures = total - successes
        durations = [e.duration_ms for e in events if e.duration_ms > 0]

        return {
            "total_invocations": total,
            "successes": successes,
            "failures": failures,
            "error_rate": failures / total if total > 0 else 0,
            "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
            "min_duration_ms": min(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
            "first_used": min(e.timestamp for e in events),
            "last_used": max(e.timestamp for e in events),
        }

    def get_unused_components(
        self, registered: list[str], hours: float = 168
    ) -> list[str]:
        """Find components that haven't been used in the given period."""
        cutoff = time.time() - hours * 3600
        used = {
            e.component_name for e in self._events if e.timestamp >= cutoff
        }
        return [name for name in registered if name not in used]

    def get_error_prone(
        self, min_error_rate: float = 0.1, min_invocations: int = 5
    ) -> list[tuple[str, float, int]]:
        """Find components with high error rates.

        Returns list of (name, error_rate, total_invocations).
        """
        counts: dict[str, int] = Counter()
        errors: dict[str, int] = Counter()
        for ev in self._events:
            counts[ev.component_name] += 1
            if not ev.success:
                errors[ev.component_name] += 1

        result = []
        for name, total in counts.items():
            if total < min_invocations:
                continue
            rate = errors.get(name, 0) / total
            if rate >= min_error_rate:
                result.append((name, rate, total))
        return sorted(result, key=lambda x: x[1], reverse=True)

    def get_performance_outliers(
        self, percentile: float = 95
    ) -> list[tuple[str, float]]:
        """Find components with response times above the given percentile."""
        durations_by_comp: dict[str, list[float]] = defaultdict(list)
        for ev in self._events:
            if ev.duration_ms > 0:
                durations_by_comp[ev.component_name].append(ev.duration_ms)

        all_durations = [d for durs in durations_by_comp.values() for d in durs]
        if not all_durations:
            return []

        all_durations.sort()
        idx = int(len(all_durations) * percentile / 100)
        idx = min(idx, len(all_durations) - 1)
        threshold = all_durations[idx]

        result = []
        for name, durs in durations_by_comp.items():
            avg = sum(durs) / len(durs)
            if avg >= threshold:
                result.append((name, avg))
        return sorted(result, key=lambda x: x[1], reverse=True)

    def get_hourly_pattern(self) -> dict[int, int]:
        """Get usage distribution by hour of day (0-23)."""
        hourly: Counter[int] = Counter()
        for ev in self._events:
            hour = datetime.fromtimestamp(ev.timestamp, tz=timezone.utc).hour
            hourly[hour] += 1
        return dict(hourly)

    def get_daily_trend(self, days: int = 7) -> list[tuple[str, int]]:
        """Get daily usage counts for the past N days.

        Returns list of (date_str, count).
        """
        now = time.time()
        cutoff = now - days * 86400
        daily: Counter[str] = Counter()
        for ev in self._events:
            if ev.timestamp >= cutoff:
                date_str = datetime.fromtimestamp(
                    ev.timestamp, tz=timezone.utc
                ).strftime("%Y-%m-%d")
                daily[date_str] += 1
        return sorted(daily.items(), key=lambda x: x[0])

    def export_events(self, hours: float | None = None) -> list[dict]:
        """Export events as serializable dicts."""
        if hours is not None:
            cutoff = time.time() - hours * 3600
            events = [e for e in self._events if e.timestamp >= cutoff]
        else:
            events = self._events
        return [
            {
                "component_name": e.component_name,
                "component_type": e.component_type,
                "action": e.action,
                "timestamp": e.timestamp,
                "duration_ms": e.duration_ms,
                "success": e.success,
                "metadata": e.metadata,
            }
            for e in events
        ]

    def clear(self) -> None:
        """Clear all tracked events."""
        self._events.clear()
