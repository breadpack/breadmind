import pytest
from breadmind.monitoring.engine import MonitoringEngine, MonitoringEvent, MonitoringRule, LoopProtector
from breadmind.monitoring.rules import (
    _check_pod_crash, _check_node_not_ready, _check_memory_high,
    _check_vm_unexpected_stop, _check_wan_down, DEFAULT_RULES,
)

# LoopProtector tests
def test_loop_protector_allows_first_action():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    assert lp.can_act_sync("pod:nginx", "restart") is True

def test_loop_protector_cooldown():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    lp.record_action_sync("pod:nginx", "restart")
    assert lp.can_act_sync("pod:nginx", "restart") is False  # in cooldown

def test_loop_protector_different_targets():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    lp.record_action_sync("pod:nginx", "restart")
    assert lp.can_act_sync("pod:redis", "restart") is True  # different target

# Rule tests
def test_check_pod_crash():
    state = {"pods": [{"name": "nginx-abc", "namespace": "default", "status": "CrashLoopBackOff", "restarts": 5}]}
    events = _check_pod_crash(state, None)
    assert len(events) == 1
    assert events[0].severity == "critical"
    assert events[0].condition == "CrashLoopBackOff"

def test_check_pod_crash_no_issue():
    state = {"pods": [{"name": "nginx-abc", "status": "Running"}]}
    events = _check_pod_crash(state, None)
    assert len(events) == 0

def test_check_node_not_ready():
    state = {"nodes": [{"name": "worker-1", "ready": False}]}
    events = _check_node_not_ready(state, None)
    assert len(events) == 1
    assert events[0].condition == "NotReady"

def test_check_memory_high():
    state = {"hosts": [{"name": "pve-node", "source": "proxmox", "memory_percent": 95}]}
    events = _check_memory_high(state, None)
    assert len(events) == 1
    assert events[0].severity == "warning"

def test_check_memory_normal():
    state = {"hosts": [{"name": "pve-node", "source": "proxmox", "memory_percent": 50}]}
    events = _check_memory_high(state, None)
    assert len(events) == 0

def test_check_vm_unexpected_stop():
    prev = {"vms": [{"vmid": 100, "name": "web", "status": "running"}]}
    state = {"vms": [{"vmid": 100, "name": "web", "status": "stopped"}]}
    events = _check_vm_unexpected_stop(state, prev)
    assert len(events) == 1
    assert events[0].condition == "unexpected_stop"

def test_check_vm_no_prev():
    state = {"vms": [{"vmid": 100, "status": "stopped"}]}
    events = _check_vm_unexpected_stop(state, None)
    assert len(events) == 0

def test_check_wan_down():
    state = {"interfaces": [{"name": "wan", "status": "down"}]}
    events = _check_wan_down(state, None)
    assert len(events) == 1
    assert events[0].severity == "critical"

def test_default_rules_exist():
    assert len(DEFAULT_RULES) == 5

# Engine tests
@pytest.mark.asyncio
async def test_engine_check_once():
    def dummy_rule(state, prev):
        return [MonitoringEvent(source="test", target="test:1", severity="info", condition="test_event")]
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="test", source="test", condition_fn=dummy_rule))
    events = await engine.check_once()
    assert len(events) == 1
    assert events[0].condition == "test_event"

@pytest.mark.asyncio
async def test_engine_start_stop():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="test", source="test", condition_fn=lambda s, p: [], interval_seconds=1))
    await engine.start()
    assert engine._running is True
    await engine.stop()
    assert engine._running is False

@pytest.mark.asyncio
async def test_engine_stop_idempotent():
    engine = MonitoringEngine()
    await engine.stop()  # Should not raise
    assert engine._running is False

@pytest.mark.asyncio
async def test_engine_start_idempotent():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="test", source="test", condition_fn=lambda s, p: [], interval_seconds=1))
    await engine.start()
    await engine.start()  # Should not create duplicate tasks
    assert engine._running is True
    assert len(engine._tasks) == 1
    await engine.stop()


# --- get_status() tests ---

def test_engine_get_status_initial():
    engine = MonitoringEngine()
    status = engine.get_status()
    assert status == {"running": False, "rules_count": 0, "tasks_count": 0}

def test_engine_get_status_with_rules():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: []))
    engine.add_rule_sync(MonitoringRule(name="r2", source="test", condition_fn=lambda s, p: []))
    status = engine.get_status()
    assert status["running"] is False
    assert status["rules_count"] == 2
    assert status["tasks_count"] == 0

@pytest.mark.asyncio
async def test_engine_get_status_running():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: [], interval_seconds=1))
    await engine.start()
    status = engine.get_status()
    assert status["running"] is True
    assert status["rules_count"] == 1
    assert status["tasks_count"] == 1
    await engine.stop()
    status = engine.get_status()
    assert status["running"] is False
    assert status["tasks_count"] == 0


# --- Dynamic rule config tests ---

def test_update_rule_interval():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: [], interval_seconds=60))
    assert engine.update_rule_interval("r1", 120) is True
    assert engine._rules[0].interval_seconds == 120

def test_update_rule_interval_not_found():
    engine = MonitoringEngine()
    assert engine.update_rule_interval("nonexistent", 120) is False

def test_enable_rule():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: [], enabled=False))
    assert engine._rules[0].enabled is False
    assert engine.enable_rule("r1") is True
    assert engine._rules[0].enabled is True

def test_disable_rule():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: []))
    assert engine._rules[0].enabled is True
    assert engine.disable_rule("r1") is True
    assert engine._rules[0].enabled is False

def test_enable_disable_not_found():
    engine = MonitoringEngine()
    assert engine.enable_rule("nonexistent") is False
    assert engine.disable_rule("nonexistent") is False

def test_get_rules_config():
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=lambda s, p: [], severity="warning", description="Test rule", interval_seconds=30))
    config = engine.get_rules_config()
    assert len(config) == 1
    assert config[0]["name"] == "r1"
    assert config[0]["description"] == "Test rule"
    assert config[0]["interval_seconds"] == 30
    assert config[0]["enabled"] is True
    assert config[0]["severity"] == "warning"

def test_update_loop_protector_config():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    engine = MonitoringEngine(loop_protector=lp)
    engine.update_loop_protector_config(cooldown_minutes=20, max_auto_actions=5)
    assert lp._cooldown_minutes == 20
    assert lp._max_auto_actions == 5

def test_update_loop_protector_config_partial():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    engine = MonitoringEngine(loop_protector=lp)
    engine.update_loop_protector_config(cooldown_minutes=15)
    assert lp._cooldown_minutes == 15
    assert lp._max_auto_actions == 3

def test_get_loop_protector_config():
    lp = LoopProtector(cooldown_minutes=10, max_auto_actions=3)
    engine = MonitoringEngine(loop_protector=lp)
    config = engine.get_loop_protector_config()
    assert config == {"cooldown_minutes": 10, "max_auto_actions": 3}

def test_get_loop_protector_config_none():
    engine = MonitoringEngine()
    # Default engine creates a LoopProtector, so config should not be empty
    config = engine.get_loop_protector_config()
    assert "cooldown_minutes" in config

@pytest.mark.asyncio
async def test_disabled_rule_skipped_in_check_once():
    call_count = 0
    def counting_rule(state, prev):
        nonlocal call_count
        call_count += 1
        return [MonitoringEvent(source="test", target="test:1", severity="info", condition="test_event")]
    engine = MonitoringEngine()
    engine.add_rule_sync(MonitoringRule(name="r1", source="test", condition_fn=counting_rule, enabled=False))
    events = await engine.check_once()
    assert len(events) == 0
    assert call_count == 0
