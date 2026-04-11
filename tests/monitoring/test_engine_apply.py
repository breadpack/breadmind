from unittest.mock import MagicMock

from breadmind.monitoring.engine import MonitoringEngine


def _make_engine():
    engine = MonitoringEngine()
    # Stub the update paths so tests don't depend on the real scheduler.
    engine.update_loop_protector_config = MagicMock()
    engine.update_rule_interval = MagicMock()
    engine.enable_rule = MagicMock()
    engine.disable_rule = MagicMock()
    return engine


async def test_apply_loop_protector_calls_update_loop_protector_config():
    engine = _make_engine()
    await engine.apply(loop_protector={"cooldown_minutes": 7, "max_auto_actions": 5})
    engine.update_loop_protector_config.assert_called_once_with(
        cooldown_minutes=7, max_auto_actions=5,
    )


async def test_apply_monitoring_config_enables_and_updates_intervals():
    engine = _make_engine()
    # Seed fake rules so the method can reason about them.
    rule_a = MagicMock()
    rule_a.name = "a"
    rule_a.enabled = True
    rule_b = MagicMock()
    rule_b.name = "b"
    rule_b.enabled = True
    engine._rules = [rule_a, rule_b]
    await engine.apply(monitoring_config={
        "rules": [
            {"name": "a", "enabled": True, "interval_seconds": 30},
            {"name": "b", "enabled": False},
        ],
    })
    engine.update_rule_interval.assert_called_once_with("a", 30)
    engine.disable_rule.assert_called_once_with("b")


async def test_apply_monitoring_config_with_no_rules_key_is_noop():
    engine = _make_engine()
    engine._rules = []
    await engine.apply(monitoring_config={})
    engine.update_rule_interval.assert_not_called()
    engine.enable_rule.assert_not_called()
    engine.disable_rule.assert_not_called()


async def test_apply_scheduler_cron_is_debug_noop():
    engine = _make_engine()
    await engine.apply(scheduler_cron={"enabled": True})
    # Should not raise, should not call any update method.
    engine.update_rule_interval.assert_not_called()


async def test_apply_webhook_endpoints_is_debug_noop():
    engine = _make_engine()
    await engine.apply(webhook_endpoints=[{"url": "https://x"}])
    engine.update_rule_interval.assert_not_called()


async def test_apply_all_four_fields_at_once():
    engine = _make_engine()
    rule_a = MagicMock()
    rule_a.name = "a"
    rule_a.enabled = True
    engine._rules = [rule_a]
    await engine.apply(
        monitoring_config={"rules": [{"name": "a", "enabled": True, "interval_seconds": 10}]},
        loop_protector={"cooldown_minutes": 3, "max_auto_actions": 2},
        scheduler_cron={"enabled": False},
        webhook_endpoints=[],
    )
    engine.update_loop_protector_config.assert_called_once()
    engine.update_rule_interval.assert_called_once_with("a", 10)
