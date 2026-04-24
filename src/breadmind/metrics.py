"""Prometheus metrics + OpenTelemetry tracer for long-running coding jobs.

Task 24 of the long-running-monitoring plan. Exposes six Counters/Histogram/
Gauge instruments for the coding-job subsystem (JobTracker, LogBuffer,
JobExecutor, retention cron) plus a shared OTel ``tracer`` for span
instrumentation.

Design notes
------------
* The :mod:`prometheus_client` and :mod:`opentelemetry` packages are listed
  as hard dependencies in ``pyproject.toml``. As a defensive measure we
  still gate the imports so unit tests and smoke paths keep working on
  slim installs — missing deps collapse to no-op stubs with the same
  public surface (``.inc()``, ``.observe()``, ``.set()``, ``.labels()``
  for metrics; ``start_as_current_span()`` context manager for the tracer).
* Metric names are NOT project-prefixed to stay consistent with the Task 24
  spec exactly: ``coding_jobs_total``, ``coding_job_duration_seconds``, etc.
* A dedicated :class:`CollectorRegistry` is avoided — instruments land on
  the default registry so the existing ``/metrics`` FastAPI handler (which
  reads the default registry) picks them up automatically.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "coding_jobs_total",
    "coding_job_duration_seconds",
    "coding_active_jobs",
    "coding_phase_log_lines_total",
    "coding_db_writer_drops_total",
    "coding_log_drops_total",
    "coding_jobs_deleted_total",
    "tracer",
]


# ---------------------------------------------------------------------------
# Prometheus metrics — real if prometheus_client is installed, else no-ops.
# ---------------------------------------------------------------------------


class _NoopMetric:
    """Drop-in for prometheus Counter/Gauge/Histogram when deps are absent.

    Supports the narrow surface the rest of the codebase touches: ``inc``,
    ``observe``, ``set``, and ``labels`` (returns self so chained calls
    like ``.labels(status="completed").inc()`` keep working).
    """

    def labels(self, *args: Any, **kwargs: Any) -> "_NoopMetric":
        return self

    def inc(self, amount: float = 1.0) -> None:  # noqa: D401
        return None

    def observe(self, value: float) -> None:  # noqa: D401
        return None

    def set(self, value: float) -> None:  # noqa: D401
        return None


try:  # pragma: no cover - exercised whenever prometheus_client is installed
    from prometheus_client import Counter, Gauge, Histogram

    _DURATION_BUCKETS = (
        1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0,
        1200.0, 1800.0, 3600.0, 7200.0,
    )

    coding_jobs_total: Any = Counter(
        "coding_jobs_total",
        "Completed coding jobs by terminal status (completed / failed / cancelled).",
        ("status",),
    )
    coding_job_duration_seconds: Any = Histogram(
        "coding_job_duration_seconds",
        "Wall-clock duration of completed coding jobs in seconds.",
        buckets=_DURATION_BUCKETS,
    )
    coding_active_jobs: Any = Gauge(
        "coding_active_jobs",
        "Number of coding jobs currently in a non-terminal state.",
    )
    coding_phase_log_lines_total: Any = Counter(
        "coding_phase_log_lines_total",
        "Total phase log lines ingested into JobTracker.append_log.",
    )
    coding_log_drops_total: Any = Counter(
        "coding_log_drops_total",
        "Log lines dropped before persistence, labelled by reason.",
        ("reason",),
    )
    coding_db_writer_drops_total: Any = Counter(
        "coding_db_writer_drops_total",
        "JobDbWriter drops by reason (queue_full | no_loop | coro_failed).",
        ("reason",),
    )
    coding_jobs_deleted_total: Any = Counter(
        "coding_jobs_deleted_total",
        "Coding jobs pruned by the daily retention cron.",
    )
except Exception:  # pragma: no cover - defensive stub path
    coding_jobs_total = _NoopMetric()
    coding_job_duration_seconds = _NoopMetric()
    coding_active_jobs = _NoopMetric()
    coding_phase_log_lines_total = _NoopMetric()
    coding_log_drops_total = _NoopMetric()
    coding_db_writer_drops_total = _NoopMetric()
    coding_jobs_deleted_total = _NoopMetric()


# ---------------------------------------------------------------------------
# OpenTelemetry tracer — real if opentelemetry-api is installed, else no-op.
# ---------------------------------------------------------------------------
#
# ``opentelemetry.trace.get_tracer`` returns a real Tracer backed by the
# globally configured TracerProvider. When no provider is configured (the
# default), the returned tracer is itself a no-op, so callers can wrap
# spans freely without runtime cost or setup. The ``try/except`` below is
# only for installs that strip the opentelemetry-api package entirely.


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
        return None

    def record_exception(self, exc: BaseException) -> None:  # noqa: D401
        return None


class _NoopTracer:
    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


try:  # pragma: no cover - exercised whenever opentelemetry-api is installed
    from opentelemetry import trace as _otel_trace

    tracer: Any = _otel_trace.get_tracer("breadmind.coding")
except Exception:  # pragma: no cover - defensive stub path
    tracer = _NoopTracer()
