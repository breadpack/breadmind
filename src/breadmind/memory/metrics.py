"""Prometheus metrics for the episodic memory pipeline (T13).

Mirrors the pattern used in :mod:`breadmind.metrics` for the coding-job
subsystem and :mod:`breadmind.kb.metrics` for the company KB: instruments
register on the prometheus_client default ``REGISTRY`` so the existing
``/metrics`` route picks them up automatically. When the prometheus_client
package is unavailable the instruments collapse to no-op stubs preserving
the public surface used by call sites (``inc``, ``observe``, ``labels``).

Metric names are locked by the Phase 1 plan and must not be renamed:

- ``breadmind_memory_signal_detected_total{kind}`` — Counter
- ``breadmind_memory_normalize_total{outcome}`` — Counter
- ``breadmind_memory_normalize_latency_seconds`` — Histogram (default buckets)
- ``breadmind_memory_recall_total{trigger}`` — Counter
- ``breadmind_memory_recall_hit_count`` — Histogram, custom buckets
- ``breadmind_org_id_lookup_total{outcome}`` — Counter (T8, hit | miss)
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "memory_signal_detected_total",
    "memory_normalize_total",
    "memory_normalize_latency_seconds",
    "memory_recall_total",
    "memory_recall_hit_count",
    "org_id_lookup_total",
]


class _NoopMetric:
    """Drop-in stub when prometheus_client is missing."""

    def labels(self, *args: Any, **kwargs: Any) -> "_NoopMetric":
        return self

    def inc(self, amount: float = 1.0) -> None:  # noqa: D401
        return None

    def observe(self, value: float) -> None:  # noqa: D401
        return None

    def set(self, value: float) -> None:  # noqa: D401
        return None


try:  # pragma: no cover - exercised whenever prometheus_client is installed
    from prometheus_client import Counter, Histogram

    _RECALL_HIT_BUCKETS = (0, 1, 2, 3, 5, 10)

    memory_signal_detected_total: Any = Counter(
        "breadmind_memory_signal_detected_total",
        "Signal events detected, by kind",
        ("kind",),
    )
    memory_normalize_total: Any = Counter(
        "breadmind_memory_normalize_total",
        "Episodic recorder normalization outcomes "
        "(recorded | skipped_by_llm | llm_failed | raw_fallback)",
        ("outcome",),
    )
    memory_normalize_latency_seconds: Any = Histogram(
        "breadmind_memory_normalize_latency_seconds",
        "EpisodicRecorder.normalize latency (seconds)",
    )
    memory_recall_total: Any = Counter(
        "breadmind_memory_recall_total",
        "Episodic recall trigger count (turn | tool)",
        ("trigger",),
    )
    memory_recall_hit_count: Any = Histogram(
        "breadmind_memory_recall_hit_count",
        "Top-K hit count per recall (0 means empty result)",
        buckets=_RECALL_HIT_BUCKETS,
    )
    org_id_lookup_total: Any = Counter(
        "breadmind_org_id_lookup_total",
        "Slack team_id → org_projects.id lookup outcomes (hit | miss)",
        ("outcome",),
    )
except Exception:  # pragma: no cover - defensive stub path
    memory_signal_detected_total = _NoopMetric()
    memory_normalize_total = _NoopMetric()
    memory_normalize_latency_seconds = _NoopMetric()
    memory_recall_total = _NoopMetric()
    memory_recall_hit_count = _NoopMetric()
    org_id_lookup_total = _NoopMetric()
