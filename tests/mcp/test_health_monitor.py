"""Tests for MCPHealthMonitor health tracking and auto-restart logic."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from breadmind.mcp.health_monitor import (
    HealthStatus,
    MCPHealthMonitor,
    ServerHealth,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_monitor(**kwargs) -> MCPHealthMonitor:
    defaults = {
        "check_interval_seconds": 30,
        "max_consecutive_failures": 3,
        "auto_restart": True,
        "response_time_threshold_ms": 5000,
    }
    defaults.update(kwargs)
    return MCPHealthMonitor(**defaults)


# ── Registration ─────────────────────────────────────────────────────


def test_register_and_get_health():
    mon = _make_monitor()
    mon.register_server("server-a")

    health = mon.get_health("server-a")
    assert health is not None
    assert health.name == "server-a"
    assert health.status == HealthStatus.UNKNOWN
    assert health.started_at > 0


def test_unregister_removes_server():
    mon = _make_monitor()
    mon.register_server("server-a")
    mon.unregister_server("server-a")

    assert mon.get_health("server-a") is None


def test_get_health_unknown_returns_none():
    mon = _make_monitor()
    assert mon.get_health("nonexistent") is None


# ── Recording checks ────────────────────────────────────────────────


def test_record_healthy_check():
    mon = _make_monitor()
    mon.register_server("s1")

    health = mon.record_check("s1", healthy=True, response_time_ms=100)

    assert health.status == HealthStatus.HEALTHY
    assert health.consecutive_failures == 0
    assert health.total_checks == 1
    assert health.total_failures == 0
    assert health.response_time_ms == 100
    assert health.last_error == ""


def test_record_unhealthy_check():
    mon = _make_monitor()
    mon.register_server("s1")

    health = mon.record_check("s1", healthy=False, error="connection refused")

    assert health.status == HealthStatus.DEGRADED  # 1 failure, not yet at threshold
    assert health.consecutive_failures == 1
    assert health.total_failures == 1
    assert health.last_error == "connection refused"


def test_consecutive_failures_become_unhealthy():
    mon = _make_monitor(max_consecutive_failures=3)
    mon.register_server("s1")

    mon.record_check("s1", healthy=False, error="err1")
    mon.record_check("s1", healthy=False, error="err2")
    health = mon.record_check("s1", healthy=False, error="err3")

    assert health.status == HealthStatus.UNHEALTHY
    assert health.consecutive_failures == 3
    assert health.total_failures == 3


def test_healthy_check_resets_consecutive_failures():
    mon = _make_monitor(max_consecutive_failures=3)
    mon.register_server("s1")

    mon.record_check("s1", healthy=False, error="e1")
    mon.record_check("s1", healthy=False, error="e2")
    health = mon.record_check("s1", healthy=True, response_time_ms=50)

    assert health.status == HealthStatus.HEALTHY
    assert health.consecutive_failures == 0
    assert health.total_failures == 2  # total still tracked


def test_slow_response_marks_degraded():
    mon = _make_monitor(response_time_threshold_ms=1000)
    mon.register_server("s1")

    health = mon.record_check("s1", healthy=True, response_time_ms=2000)

    assert health.status == HealthStatus.DEGRADED


def test_record_check_unregistered_raises():
    mon = _make_monitor()
    with pytest.raises(KeyError, match="not registered"):
        mon.record_check("ghost", healthy=True)


# ── Needs restart ────────────────────────────────────────────────────


def test_needs_restart_after_max_failures():
    mon = _make_monitor(max_consecutive_failures=2)
    mon.register_server("s1")

    mon.record_check("s1", healthy=False, error="e1")
    assert mon.needs_restart("s1") is False

    mon.record_check("s1", healthy=False, error="e2")
    assert mon.needs_restart("s1") is True


def test_needs_restart_disabled():
    mon = _make_monitor(auto_restart=False, max_consecutive_failures=1)
    mon.register_server("s1")
    mon.record_check("s1", healthy=False, error="e1")

    assert mon.needs_restart("s1") is False


def test_needs_restart_unknown_server():
    mon = _make_monitor()
    assert mon.needs_restart("nope") is False


# ── Restart recording ───────────────────────────────────────────────


def test_record_restart_resets_state():
    mon = _make_monitor(max_consecutive_failures=2)
    mon.register_server("s1")
    mon.record_check("s1", healthy=False, error="e1")
    mon.record_check("s1", healthy=False, error="e2")

    mon.record_restart("s1")
    health = mon.get_health("s1")

    assert health.restart_count == 1
    assert health.consecutive_failures == 0
    assert health.status == HealthStatus.UNKNOWN
    assert health.last_error == ""


def test_record_restart_unregistered_raises():
    mon = _make_monitor()
    with pytest.raises(KeyError, match="not registered"):
        mon.record_restart("ghost")


# ── Summary ──────────────────────────────────────────────────────────


def test_get_summary():
    mon = _make_monitor(max_consecutive_failures=2)
    mon.register_server("healthy1")
    mon.register_server("healthy2")
    mon.register_server("unhealthy1")
    mon.register_server("unknown1")

    mon.record_check("healthy1", healthy=True, response_time_ms=50)
    mon.record_check("healthy2", healthy=True, response_time_ms=100)
    mon.record_check("unhealthy1", healthy=False, error="e1")
    mon.record_check("unhealthy1", healthy=False, error="e2")

    summary = mon.get_summary()
    assert summary["total"] == 4
    assert summary["healthy"] == 2
    assert summary["unhealthy"] == 1
    assert summary["unknown"] == 1  # unknown1 never checked


def test_get_all_health():
    mon = _make_monitor()
    mon.register_server("a")
    mon.register_server("b")

    all_h = mon.get_all_health()
    assert len(all_h) == 2
    names = {h.name for h in all_h}
    assert names == {"a", "b"}


# ── Uptime ───────────────────────────────────────────────────────────


def test_get_uptime():
    mon = _make_monitor()
    mon.register_server("s1")

    uptime = mon.get_uptime("s1")
    assert uptime >= 0


def test_get_uptime_unknown_server():
    mon = _make_monitor()
    assert mon.get_uptime("nope") == 0


# ── Properties ───────────────────────────────────────────────────────


def test_properties():
    mon = _make_monitor(check_interval_seconds=45, auto_restart=False)
    assert mon.running is False
    assert mon.check_interval == 45
    assert mon.auto_restart_enabled is False
