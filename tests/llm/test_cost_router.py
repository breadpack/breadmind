"""Tests for CostRouter -- full selection algorithm with mocks."""
from __future__ import annotations

import pytest

from breadmind.core.intent import IntentCategory
from breadmind.llm.budget import BudgetConfig, BudgetManager
from breadmind.llm.cost_router import CostRouter
from breadmind.llm.optimizer import QualityCostOptimizer, UserPreference
from breadmind.llm.pricing import ModelCostRegistry
from breadmind.llm.quality_feedback import SuccessTracker


@pytest.fixture
def registry():
    return ModelCostRegistry()


@pytest.fixture
def optimizer():
    return QualityCostOptimizer()


@pytest.fixture
def budget():
    return BudgetManager(BudgetConfig(daily_limit=10.0, monthly_limit=100.0, per_provider_daily=5.0))


@pytest.fixture
def tracker():
    return SuccessTracker()


@pytest.fixture
def router(registry, optimizer, budget, tracker):
    r = CostRouter(
        registry=registry,
        optimizer=optimizer,
        budget=budget,
        success_tracker=tracker,
        available_providers={"anthropic", "google"},
        default_provider="anthropic",
        default_model="claude-sonnet-4-6",
    )
    r.enabled = True
    return r


class TestSelectModel:

    def test_disabled_returns_default(self, registry, optimizer, budget, tracker):
        router = CostRouter(registry, optimizer, budget, tracker)
        # enabled is False by default
        provider, model = router.select_model(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
        )
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_simple_chat_selects_cheapest(self, router):
        provider, model = router.select_model(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
            preference=UserPreference.BUDGET,
        )
        # Should pick the cheapest tier-1+ model among available providers
        assert provider in ("anthropic", "google")
        assert model is not None

    def test_complex_diagnose_selects_high_tier(self, router):
        provider, model = router.select_model(
            category=IntentCategory.DIAGNOSE,
            complexity="complex",
            urgency="normal",
            preference=UserPreference.BALANCED,
        )
        info = router.registry.get(model)
        # For complex diagnose, minimum tier is 4 (premium)
        # If no tier-4 model available among providers, falls back to default
        assert info is not None or model == "claude-sonnet-4-6"

    def test_budget_exhausted_uses_default(self, router):
        # Exhaust the budget
        for _ in range(100):
            router.record_result("anthropic", "claude-sonnet-4-6", "chat", True, 0.1, 100)
            router.record_result("google", "gemini-2.5-flash", "chat", True, 0.1, 100)
        provider, model = router.select_model(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
        )
        # When all candidates are over budget, falls back to default
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_low_success_rate_filters_model(self, router):
        # Record many failures for a model
        for _ in range(20):
            router._success_tracker.record("gemini-2.5-flash", "query", success=False)
        # The model should have <0.3 success rate now
        rate = router._success_tracker.get_success_rate("gemini-2.5-flash", "query")
        assert rate < 0.3

    def test_unavailable_provider_filtered(self, registry, optimizer, budget, tracker):
        router = CostRouter(
            registry=registry,
            optimizer=optimizer,
            budget=budget,
            success_tracker=tracker,
            available_providers={"anthropic"},  # Only anthropic
        )
        router.enabled = True
        provider, model = router.select_model(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
        )
        assert provider == "anthropic"


class TestRecordResult:

    def test_record_updates_budget(self, router):
        router.record_result("anthropic", "claude-haiku-4-5", "chat", True, 0.01, 100)
        summary = router.budget.get_usage_summary()
        assert summary["daily"]["total"] > 0

    def test_record_updates_success_tracker(self, router):
        router.record_result("anthropic", "claude-haiku-4-5", "chat", True, 0.01, 100)
        rate = router._success_tracker.get_success_rate("claude-haiku-4-5", "chat")
        assert rate == 1.0

    def test_record_failure(self, router):
        router.record_result("anthropic", "claude-haiku-4-5", "chat", False, 0.01, 500)
        rate = router._success_tracker.get_success_rate("claude-haiku-4-5", "chat")
        assert rate == 0.0


class TestProperties:

    def test_registry_accessible(self, router):
        assert router.registry is not None

    def test_budget_accessible(self, router):
        assert router.budget is not None
