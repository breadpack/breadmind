"""Prometheus metrics coverage for Task 24.

Confirms the six metric instruments are exported with the expected
surface (``inc`` / ``observe`` / ``set``) and that the active-jobs Gauge
is nudged by JobTracker lifecycle transitions.
"""
from __future__ import annotations


def test_metrics_exposed() -> None:
    from breadmind.metrics import (
        coding_active_jobs,
        coding_job_duration_seconds,
        coding_jobs_deleted_total,
        coding_jobs_total,
        coding_log_drops_total,
        coding_phase_log_lines_total,
    )

    # Counter-like instruments expose ``inc``; Histogram exposes ``observe``;
    # Gauge exposes ``set``. ``labels(...)`` returns something with ``inc``
    # for the labelled Counters.
    assert hasattr(coding_jobs_total, "inc") or hasattr(coding_jobs_total, "labels")
    assert hasattr(coding_job_duration_seconds, "observe")
    assert hasattr(coding_active_jobs, "set")
    assert hasattr(coding_phase_log_lines_total, "inc")
    assert hasattr(coding_log_drops_total, "labels")
    assert hasattr(coding_jobs_deleted_total, "inc")


async def test_active_gauge_tracks_running(test_db) -> None:
    """Gauge rises on ``create_job`` and drops back on ``complete_job``.

    Note: the Gauge is process-global (prometheus_client registry is
    global) while ``get_active_jobs()`` is per-tracker.  Prior tests
    that never call ``complete_job`` can leave the Gauge pinned at a
    non-zero value, so this test resets it to zero first and then
    asserts exact before/after values.
    """
    from breadmind.coding.job_store import JobStore
    from breadmind.coding.job_tracker import JobTracker
    from breadmind.metrics import coding_active_jobs

    def _value() -> float:
        raw = getattr(coding_active_jobs, "_value", None)
        if raw is None:
            return 0.0
        return raw.get()

    # Reset the process-global Gauge so prior-test contamination doesn't
    # leak into our before/after assertions.
    coding_active_jobs.set(0)

    tracker = JobTracker()
    tracker.bind_store(JobStore(test_db))

    before = _value()
    assert before == 0

    tracker.create_job("metrics-j1", "p", "c", "x")
    tracker.set_phases("metrics-j1", [{"step": 1, "title": "t"}])
    tracker.start_phase("metrics-j1", 1)

    during = _value()
    assert during >= 1

    tracker.complete_phase("metrics-j1", 1, success=True)
    tracker.complete_job("metrics-j1", success=True)

    after = _value()
    # Back to zero — our tracker has no other active jobs.
    assert after == 0


def test_coding_db_writer_drops_total_exists() -> None:
    from breadmind import metrics
    assert hasattr(metrics, "coding_db_writer_drops_total")
    # Verify labels API works (no-op fallback path also supports .labels)
    metric = metrics.coding_db_writer_drops_total.labels(reason="queue_full")
    metric.inc()  # must not raise
