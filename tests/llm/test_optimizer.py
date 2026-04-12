"""Tests for QualityCostOptimizer -- intent x complexity mappings and preferences."""
from __future__ import annotations

import pytest

from breadmind.core.intent import IntentCategory
from breadmind.llm.optimizer import (
    QualityCostOptimizer,
    UserPreference,
    get_min_quality_tier,
)
from breadmind.llm.pricing import (
    ModelCostRegistry,
)


@pytest.fixture
def registry():
    r = ModelCostRegistry()
    return r


@pytest.fixture
def optimizer():
    return QualityCostOptimizer()


class TestQualityMatrix:
    """Test get_min_quality_tier for all intent x complexity combinations."""

    def test_chat_simple_is_low(self):
        assert get_min_quality_tier(IntentCategory.CHAT, "simple") == 1

    def test_chat_complex_is_medium(self):
        assert get_min_quality_tier(IntentCategory.CHAT, "complex") == 2

    def test_diagnose_complex_is_premium(self):
        assert get_min_quality_tier(IntentCategory.DIAGNOSE, "complex") == 4

    def test_diagnose_moderate_is_high(self):
        assert get_min_quality_tier(IntentCategory.DIAGNOSE, "moderate") == 3

    def test_coding_complex_is_premium(self):
        assert get_min_quality_tier(IntentCategory.CODING, "complex") == 4

    def test_coding_simple_is_medium(self):
        assert get_min_quality_tier(IntentCategory.CODING, "simple") == 2

    def test_execute_moderate_is_medium(self):
        assert get_min_quality_tier(IntentCategory.EXECUTE, "moderate") == 2

    def test_learn_simple_is_low(self):
        assert get_min_quality_tier(IntentCategory.LEARN, "simple") == 1

    def test_unknown_complexity_returns_default(self):
        # Unknown complexity defaults to tier 2
        assert get_min_quality_tier(IntentCategory.QUERY, "unknown") == 2


class TestPreferenceEffects:
    """Test that user preference shifts the tier."""

    def test_budget_lowers_tier(self):
        base = get_min_quality_tier(IntentCategory.QUERY, "moderate", UserPreference.BALANCED)
        budget = get_min_quality_tier(IntentCategory.QUERY, "moderate", UserPreference.BUDGET)
        assert budget <= base

    def test_quality_raises_tier(self):
        base = get_min_quality_tier(IntentCategory.QUERY, "moderate", UserPreference.BALANCED)
        quality = get_min_quality_tier(IntentCategory.QUERY, "moderate", UserPreference.QUALITY)
        assert quality >= base

    def test_budget_clamps_to_1(self):
        # CHAT/simple is tier 1, budget would try 0 but should clamp to 1
        assert get_min_quality_tier(IntentCategory.CHAT, "simple", UserPreference.BUDGET) == 1

    def test_quality_clamps_to_4(self):
        # DIAGNOSE/complex is tier 4, quality would try 5 but should clamp to 4
        assert get_min_quality_tier(IntentCategory.DIAGNOSE, "complex", UserPreference.QUALITY) == 4


class TestSelectCandidates:
    """Test QualityCostOptimizer.select_candidates."""

    def test_returns_sorted_cheapest_first(self, optimizer, registry):
        candidates = optimizer.select_candidates(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
            preference=UserPreference.BALANCED,
            registry=registry,
        )
        assert len(candidates) > 0
        costs = [c.pricing.input + c.pricing.output for c in candidates]
        assert costs == sorted(costs)

    def test_urgency_bumps_tier(self, optimizer, registry):
        normal = optimizer.select_candidates(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
            preference=UserPreference.BALANCED,
            registry=registry,
        )
        critical = optimizer.select_candidates(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="critical",
            preference=UserPreference.BALANCED,
            registry=registry,
        )
        # Critical should have fewer (higher tier) candidates
        assert len(critical) <= len(normal)

    def test_needs_thinking_filters(self, optimizer, registry):
        candidates = optimizer.select_candidates(
            category=IntentCategory.QUERY,
            complexity="simple",
            urgency="normal",
            preference=UserPreference.BALANCED,
            registry=registry,
            needs_thinking=True,
        )
        for c in candidates:
            assert c.capability.supports_thinking is True

    def test_empty_registry_returns_empty(self, optimizer):
        empty = ModelCostRegistry()
        empty._models.clear()
        candidates = optimizer.select_candidates(
            category=IntentCategory.CHAT,
            complexity="simple",
            urgency="normal",
            preference=UserPreference.BALANCED,
            registry=empty,
        )
        assert candidates == []
