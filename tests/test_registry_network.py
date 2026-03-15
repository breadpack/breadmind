# tests/test_registry_network.py
import pytest
from datetime import datetime, timezone
from breadmind.network.registry import (
    AgentRegistry, AgentInfo, AgentStatus, RoleDefinition,
)

@pytest.fixture
def registry():
    return AgentRegistry()

def test_register_agent(registry):
    info = registry.register("worker-1", host="192.168.1.10", environment={"os": "linux"})
    assert isinstance(info, AgentInfo)
    assert info.agent_id == "worker-1"
    assert info.status == AgentStatus.REGISTERING

def test_set_agent_status(registry):
    registry.register("worker-1", host="host1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    info = registry.get("worker-1")
    assert info.status == AgentStatus.ACTIVE

def test_update_heartbeat(registry):
    registry.register("worker-1", host="host1")
    registry.update_heartbeat("worker-1", {"cpu": 0.5, "memory": 0.7})
    info = registry.get("worker-1")
    assert info.last_heartbeat is not None
    assert info.last_metrics["cpu"] == 0.5

def test_assign_role(registry):
    registry.register("worker-1", host="host1")
    role = RoleDefinition(
        name="k8s-monitor",
        tools=["shell_exec"],
        schedules=[],
        policies={"auto_actions": [], "require_approval": [], "blocked": []},
    )
    registry.assign_role("worker-1", role)
    info = registry.get("worker-1")
    assert "k8s-monitor" in [r.name for r in info.roles]

def test_remove_role(registry):
    registry.register("worker-1", host="host1")
    role = RoleDefinition(name="test-role", tools=[], schedules=[], policies={})
    registry.assign_role("worker-1", role)
    registry.remove_role("worker-1", "test-role")
    info = registry.get("worker-1")
    assert len(info.roles) == 0

def test_list_online_agents(registry):
    registry.register("w1", host="h1")
    registry.register("w2", host="h2")
    registry.set_status("w1", AgentStatus.ACTIVE)
    registry.set_status("w2", AgentStatus.OFFLINE)
    online = registry.list_by_status(AgentStatus.ACTIVE)
    assert len(online) == 1
    assert online[0].agent_id == "w1"

def test_get_unknown_agent_returns_none(registry):
    assert registry.get("nonexistent") is None

def test_detect_offline_agents(registry):
    registry.register("w1", host="h1")
    registry.set_status("w1", AgentStatus.ACTIVE)
    # Simulate stale heartbeat by setting it to past
    registry._agents["w1"].last_heartbeat = datetime(2020, 1, 1, tzinfo=timezone.utc)
    offline = registry.detect_offline(threshold_seconds=90)
    assert "w1" in offline
