"""Tests for BudgetManager -- limits, alerts, period rollover."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from breadmind.llm.budget import BudgetConfig, BudgetManager


@pytest.fixture
def budget():
    config = BudgetConfig(
        daily_limit=1.0,
        monthly_limit=10.0,
        per_provider_daily=0.5,
        alert_thresholds=[0.5, 0.8],
    )
    return BudgetManager(config)


class TestRecordAndAfford:

    def test_record_cost_updates_totals(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.1)
        summary = budget.get_usage_summary()
        assert abs(summary["daily"]["total"] - 0.1) < 0.0001
        assert abs(summary["monthly"]["total"] - 0.1) < 0.0001

    def test_record_cost_tracks_provider(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.1)
        budget.record_cost("google", "gemini-2.5-flash", 0.05)
        summary = budget.get_usage_summary()
        assert abs(summary["daily"]["by_provider"]["anthropic"] - 0.1) < 0.0001
        assert abs(summary["daily"]["by_provider"]["google"] - 0.05) < 0.0001

    def test_record_cost_tracks_model(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.1)
        summary = budget.get_usage_summary()
        assert "claude-haiku-4-5" in summary["daily"]["by_model"]

    def test_can_afford_within_limit(self, budget):
        assert budget.can_afford("anthropic", 0.3) is True

    def test_can_afford_exceeds_daily_limit(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.9)
        assert budget.can_afford("anthropic", 0.2) is False

    def test_can_afford_exceeds_provider_daily(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.45)
        # Per-provider limit is 0.5
        assert budget.can_afford("anthropic", 0.1) is False

    def test_can_afford_different_provider_ok(self, budget):
        budget.record_cost("anthropic", "claude-haiku-4-5", 0.45)
        # Different provider has its own limit
        assert budget.can_afford("google", 0.1) is True

    def test_can_afford_exceeds_monthly_limit(self, budget):
        # Monthly limit is 10.0
        for _ in range(20):
            budget.record_cost("anthropic", "claude-haiku-4-5", 0.45)
        assert budget.can_afford("anthropic", 2.0) is False


class TestAlerts:

    def test_no_alerts_below_threshold(self, budget):
        budget.record_cost("anthropic", "model", 0.1)
        alerts = budget.check_alerts()
        assert len(alerts) == 0

    def test_alert_at_50_percent(self, budget):
        budget.record_cost("anthropic", "model", 0.55)
        alerts = budget.check_alerts()
        assert any("50%" in a for a in alerts)

    def test_alert_at_80_percent(self, budget):
        budget.record_cost("anthropic", "model", 0.85)
        alerts = budget.check_alerts()
        assert any("80%" in a for a in alerts)

    def test_alerts_not_repeated(self, budget):
        budget.record_cost("anthropic", "model", 0.55)
        alerts1 = budget.check_alerts()
        alerts2 = budget.check_alerts()
        # First call should return alerts, second should not (already alerted)
        assert len(alerts1) > 0
        assert len(alerts2) == 0

    def test_monthly_alert(self, budget):
        # Monthly limit=10.0, threshold 50% = 5.0
        budget.record_cost("anthropic", "model", 5.5)
        alerts = budget.check_alerts()
        monthly_alerts = [a for a in alerts if "Monthly" in a]
        assert len(monthly_alerts) > 0


class TestPeriodRollover:

    def test_daily_rollover(self, budget):
        budget.record_cost("anthropic", "model", 0.5)
        assert budget.get_usage_summary()["daily"]["total"] > 0

        # Simulate next day
        tomorrow = date.today().replace(day=date.today().day + 1) if date.today().day < 28 else date.today()
        # Only test rollover logic if we can safely increment day
        if tomorrow != date.today():
            with patch("breadmind.llm.budget.date") as mock_date:
                mock_date.today.return_value = tomorrow
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
                budget._maybe_rollover()
                assert budget._daily.total == 0.0

    def test_request_count(self, budget):
        budget.record_cost("a", "m", 0.01)
        budget.record_cost("a", "m", 0.01)
        budget.record_cost("a", "m", 0.01)
        summary = budget.get_usage_summary()
        assert summary["daily"]["request_count"] == 3
        assert summary["monthly"]["request_count"] == 3


class TestUsageSummary:

    def test_summary_structure(self, budget):
        summary = budget.get_usage_summary()
        assert "daily" in summary
        assert "monthly" in summary
        assert "total" in summary["daily"]
        assert "limit" in summary["daily"]
        assert "remaining" in summary["daily"]
        assert "by_provider" in summary["daily"]
        assert "by_model" in summary["daily"]

    def test_remaining_decreases(self, budget):
        before = budget.get_usage_summary()["daily"]["remaining"]
        budget.record_cost("a", "m", 0.3)
        after = budget.get_usage_summary()["daily"]["remaining"]
        assert after < before


class TestDefaultConfig:

    def test_default_config(self):
        bm = BudgetManager()
        assert bm.config.daily_limit == 10.0
        assert bm.config.monthly_limit == 200.0
        assert bm.auto_downgrade is True
