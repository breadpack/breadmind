"""Tests for health_dashboard module."""

from __future__ import annotations

import time

import pytest

from breadmind.tools.health_dashboard import (
    ComponentHealth,
    ComponentStatus,
    DashboardSnapshot,
    HealthDashboard,
)


@pytest.fixture
def dashboard() -> HealthDashboard:
    return HealthDashboard()


# -- register / unregister --


def test_register_returns_component(dashboard: HealthDashboard):
    comp = dashboard.register("my_tool", "tool")
    assert comp.name == "my_tool"
    assert comp.component_type == "tool"
    assert comp.status == ComponentStatus.ACTIVE


def test_register_with_custom_status(dashboard: HealthDashboard):
    comp = dashboard.register("srv", "mcp_server", status=ComponentStatus.INACTIVE)
    assert comp.status == ComponentStatus.INACTIVE


def test_unregister_removes_component(dashboard: HealthDashboard):
    dashboard.register("x", "tool")
    dashboard.unregister("x")
    assert dashboard.get_component("x") is None


def test_unregister_nonexistent_is_noop(dashboard: HealthDashboard):
    dashboard.unregister("nonexistent")  # should not raise


# -- update_status --


def test_update_status(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.update_status("t", ComponentStatus.ERROR, error="timeout")
    comp = dashboard.get_component("t")
    assert comp is not None
    assert comp.status == ComponentStatus.ERROR
    assert comp.last_error == "timeout"
    assert comp.error_count == 1


def test_update_status_unknown_component(dashboard: HealthDashboard):
    # Should not raise
    dashboard.update_status("missing", ComponentStatus.ACTIVE)


# -- record_use --


def test_record_use_increments_counts(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.record_use("t", response_time_ms=100)
    dashboard.record_use("t", response_time_ms=200)
    comp = dashboard.get_component("t")
    assert comp is not None
    assert comp.use_count == 2
    assert comp.avg_response_ms == 150.0


def test_record_use_failure_increments_errors(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.record_use("t", success=False)
    comp = dashboard.get_component("t")
    assert comp is not None
    assert comp.error_count == 1
    assert comp.use_count == 1


def test_record_use_unknown_is_noop(dashboard: HealthDashboard):
    dashboard.record_use("ghost", response_time_ms=50)  # should not raise


# -- get_snapshot --


def test_get_snapshot_counts(dashboard: HealthDashboard):
    dashboard.register("a", "tool")
    dashboard.register("b", "skill")
    dashboard.register("c", "mcp_server", status=ComponentStatus.ERROR)
    dashboard.register("d", "plugin", status=ComponentStatus.DEGRADED)
    dashboard.register("e", "tool", status=ComponentStatus.INACTIVE)

    snap = dashboard.get_snapshot()
    assert snap.total_components == 5
    assert snap.active == 2
    assert snap.inactive == 1
    assert snap.errors == 1
    assert snap.degraded == 1
    assert snap.tools_active == 1
    assert snap.skills_active == 1
    assert snap.mcp_servers_active == 0
    assert snap.plugins_active == 0


def test_snapshot_updates_uptime(dashboard: HealthDashboard):
    comp = dashboard.register("t", "tool")
    # Fake an earlier registration time
    comp._registered_at = time.time() - 60
    snap = dashboard.get_snapshot()
    matched = [c for c in snap.components if c.name == "t"]
    assert len(matched) == 1
    assert matched[0].uptime_seconds >= 59


# -- get_by_type / get_by_status --


def test_get_by_type(dashboard: HealthDashboard):
    dashboard.register("a", "tool")
    dashboard.register("b", "skill")
    dashboard.register("c", "tool")
    assert len(dashboard.get_by_type("tool")) == 2
    assert len(dashboard.get_by_type("skill")) == 1
    assert len(dashboard.get_by_type("plugin")) == 0


def test_get_by_status(dashboard: HealthDashboard):
    dashboard.register("a", "tool")
    dashboard.register("b", "tool", status=ComponentStatus.ERROR)
    assert len(dashboard.get_by_status(ComponentStatus.ACTIVE)) == 1
    assert len(dashboard.get_by_status(ComponentStatus.ERROR)) == 1


# -- alerts --


def test_alert_on_error_status(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.update_status("t", ComponentStatus.ERROR, error="crash")
    alerts = dashboard.get_alerts()
    assert len(alerts) >= 1
    assert alerts[-1]["component"] == "t"
    assert alerts[-1]["new_status"] == "error"


def test_alert_on_status_change(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.update_status("t", ComponentStatus.INACTIVE)
    alerts = dashboard.get_alerts()
    assert any(a["component"] == "t" and a["new_status"] == "inactive" for a in alerts)


def test_no_alert_on_same_status(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    initial_count = len(dashboard.get_alerts())
    dashboard.update_status("t", ComponentStatus.ACTIVE)
    assert len(dashboard.get_alerts()) == initial_count


# -- trends --


def test_get_trends_returns_history(dashboard: HealthDashboard):
    dashboard.register("t", "tool")
    dashboard.get_snapshot()
    dashboard.get_snapshot()
    trends = dashboard.get_trends(periods=5)
    assert len(trends) >= 2


# -- render_text --


def test_render_text_contains_component_names(dashboard: HealthDashboard):
    dashboard.register("shell_exec", "tool")
    dashboard.register("mcp_k8s", "mcp_server", status=ComponentStatus.ERROR)
    text = dashboard.render_text()
    assert "shell_exec" in text
    assert "mcp_k8s" in text
    assert "[!!]" in text
    assert "Health Dashboard" in text
