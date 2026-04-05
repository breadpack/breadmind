"""Prometheus-compatible metrics registry.

Implements COUNTER, GAUGE, and HISTOGRAM metric types with Prometheus
text exposition format output.  No external dependencies required.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MetricType(Enum):
    """Supported Prometheus metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


# Default histogram buckets (matches Prometheus client defaults).
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


@dataclass
class Metric:
    """A single metric sample."""

    name: str
    type: MetricType
    help_text: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


def _labels_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    """Convert labels dict to a hashable key."""
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def _format_labels(labels: dict[str, str]) -> str:
    """Format labels as Prometheus label string: {k1="v1",k2="v2"}."""
    if not labels:
        return ""
    parts = ",".join(
        f'{k}="{v}"' for k, v in sorted(labels.items())
    )
    return "{" + parts + "}"


def _format_value(v: float) -> str:
    """Format a float value for Prometheus exposition."""
    if math.isinf(v):
        return "+Inf" if v > 0 else "-Inf"
    if v == int(v) and not math.isnan(v):
        return str(int(v))
    return f"{v:.6g}"


@dataclass
class _HistogramData:
    """Internal storage for a single histogram label-set."""

    buckets: tuple[float, ...]
    bucket_counts: list[int] = field(default_factory=list)
    count: int = 0
    total: float = 0.0

    def __post_init__(self):
        if not self.bucket_counts:
            self.bucket_counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.bucket_counts[i] += 1
                break


class MetricsRegistry:
    """Thread-safe metrics registry with Prometheus text format output."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {name: {labels_key: value}}
        self._counters: dict[str, dict[tuple, float]] = {}
        self._gauges: dict[str, dict[tuple, float]] = {}
        self._histograms: dict[str, dict[tuple, _HistogramData]] = {}
        # {name: (MetricType, help_text)}
        self._meta: dict[str, tuple[MetricType, str]] = {}
        # {name: {labels_key: labels_dict}}
        self._labels: dict[str, dict[tuple, dict[str, str]]] = {}

    # ── Public API ────────────────────────────────────────────────────

    def counter(
        self,
        name: str,
        help_text: str = "",
        labels: dict[str, str] | None = None,
        value: float = 1.0,
    ) -> None:
        """Increment a counter by *value* (default 1)."""
        key = _labels_key(labels)
        with self._lock:
            self._meta.setdefault(name, (MetricType.COUNTER, help_text))
            bucket = self._counters.setdefault(name, {})
            bucket[key] = bucket.get(key, 0.0) + value
            self._labels.setdefault(name, {})[key] = labels or {}

    def gauge(
        self,
        name: str,
        help_text: str = "",
        value: float = 0.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge to *value*."""
        key = _labels_key(labels)
        with self._lock:
            self._meta.setdefault(name, (MetricType.GAUGE, help_text))
            self._gauges.setdefault(name, {})[key] = value
            self._labels.setdefault(name, {})[key] = labels or {}

    def histogram_observe(
        self,
        name: str,
        help_text: str = "",
        value: float = 0.0,
        labels: dict[str, str] | None = None,
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        """Record an observation in a histogram."""
        key = _labels_key(labels)
        use_buckets = buckets or DEFAULT_BUCKETS
        with self._lock:
            self._meta.setdefault(name, (MetricType.HISTOGRAM, help_text))
            bucket_map = self._histograms.setdefault(name, {})
            if key not in bucket_map:
                bucket_map[key] = _HistogramData(buckets=use_buckets)
            bucket_map[key].observe(value)
            self._labels.setdefault(name, {})[key] = labels or {}

    # ── Format helpers ────────────────────────────────────────────────

    def format_prometheus(self) -> str:
        """Return all metrics in Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            for name in sorted(self._meta):
                mtype, help_text = self._meta[name]
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {mtype.value}")

                if mtype is MetricType.COUNTER:
                    for key, val in sorted(self._counters.get(name, {}).items()):
                        lbl = _format_labels(self._labels[name][key])
                        lines.append(f"{name}{lbl} {_format_value(val)}")

                elif mtype is MetricType.GAUGE:
                    for key, val in sorted(self._gauges.get(name, {}).items()):
                        lbl = _format_labels(self._labels[name][key])
                        lines.append(f"{name}{lbl} {_format_value(val)}")

                elif mtype is MetricType.HISTOGRAM:
                    for key, hdata in sorted(
                        self._histograms.get(name, {}).items(),
                    ):
                        base_labels = self._labels[name][key]
                        cumulative = 0
                        for i, bound in enumerate(hdata.buckets):
                            cumulative += hdata.bucket_counts[i]
                            blabels = {**base_labels, "le": _format_value(bound)}
                            lines.append(
                                f"{name}_bucket{_format_labels(blabels)} "
                                f"{_format_value(cumulative)}"
                            )
                        # +Inf bucket
                        inf_labels = {**base_labels, "le": "+Inf"}
                        lines.append(
                            f"{name}_bucket{_format_labels(inf_labels)} "
                            f"{_format_value(hdata.count)}"
                        )
                        lbl = _format_labels(base_labels)
                        lines.append(
                            f"{name}_sum{lbl} {_format_value(hdata.total)}"
                        )
                        lines.append(
                            f"{name}_count{lbl} {_format_value(hdata.count)}"
                        )

                lines.append("")  # blank line between metric families

        return "\n".join(lines)

    def format_json(self) -> dict[str, Any]:
        """Return all metrics as a JSON-serialisable dict."""
        result: dict[str, Any] = {}
        with self._lock:
            for name in sorted(self._meta):
                mtype, help_text = self._meta[name]
                samples: list[dict[str, Any]] = []

                if mtype is MetricType.COUNTER:
                    for key, val in sorted(
                        self._counters.get(name, {}).items(),
                    ):
                        samples.append({
                            "labels": dict(self._labels[name][key]),
                            "value": val,
                        })

                elif mtype is MetricType.GAUGE:
                    for key, val in sorted(
                        self._gauges.get(name, {}).items(),
                    ):
                        samples.append({
                            "labels": dict(self._labels[name][key]),
                            "value": val,
                        })

                elif mtype is MetricType.HISTOGRAM:
                    for key, hdata in sorted(
                        self._histograms.get(name, {}).items(),
                    ):
                        cumulative = 0
                        bucket_values: dict[str, int] = {}
                        for i, bound in enumerate(hdata.buckets):
                            cumulative += hdata.bucket_counts[i]
                            bucket_values[_format_value(bound)] = cumulative
                        bucket_values["+Inf"] = hdata.count
                        samples.append({
                            "labels": dict(self._labels[name][key]),
                            "buckets": bucket_values,
                            "sum": hdata.total,
                            "count": hdata.count,
                        })

                result[name] = {
                    "type": mtype.value,
                    "help": help_text,
                    "samples": samples,
                }

        return result


# ── Path normalizer ───────────────────────────────────────────────────

# Patterns that match numeric or UUID-like path segments.
_ID_PATTERNS = [
    (re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "/{uuid}"),
    (re.compile(r"/\d+"), "/{id}"),
]


def normalize_path(path: str) -> str:
    """Normalize URL path to reduce cardinality.

    Replaces numeric and UUID segments with placeholders:
    ``/api/v1/chat/123`` -> ``/api/v1/chat/{id}``
    ``/api/v1/job/550e8400-...`` -> ``/api/v1/job/{uuid}``
    """
    for pattern, replacement in _ID_PATTERNS:
        path = pattern.sub(replacement, path)
    return path


# ── Singleton ─────────────────────────────────────────────────────────

_global_registry: MetricsRegistry | None = None
_registry_lock = threading.Lock()


def get_metrics_registry() -> MetricsRegistry:
    """Return the global MetricsRegistry singleton."""
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = MetricsRegistry()
    return _global_registry
