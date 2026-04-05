"""Tests for per-session cost budget."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from breadmind.core.cost_budget import BudgetExhaustedError, CostBudget, CostEntry


async def test_no_budget_remaining_is_none():
    budget = CostBudget()
    assert budget.remaining is None
    assert budget.is_exhausted is False


async def test_record_and_total():
    budget = CostBudget()
    entry = budget.record("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert isinstance(entry, CostEntry)
    assert entry.cost_usd > 0
    assert budget.total_cost == entry.cost_usd


async def test_estimate_cost_known_model():
    budget = CostBudget()
    cost = budget.estimate_cost("claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000)
    # 0.80 + 4.0 = 4.80
    assert abs(cost - 4.80) < 0.01


async def test_estimate_cost_unknown_model():
    budget = CostBudget()
    cost = budget.estimate_cost("unknown-model", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0


async def test_budget_exhausted():
    budget = CostBudget(max_budget_usd=0.001)
    budget.record("claude-opus-4-6", input_tokens=10_000, output_tokens=10_000)
    assert budget.is_exhausted is True
    assert budget.remaining == 0.0


async def test_check_budget_raises():
    budget = CostBudget(max_budget_usd=0.0)
    budget.record("claude-sonnet-4-6", input_tokens=100, output_tokens=100)
    with pytest.raises(BudgetExhaustedError) as exc_info:
        budget.check_budget()
    assert exc_info.value.budget == 0.0
    assert exc_info.value.spent > 0


async def test_check_budget_ok():
    budget = CostBudget(max_budget_usd=100.0)
    budget.record("claude-sonnet-4-6", input_tokens=100, output_tokens=100)
    budget.check_budget()  # should not raise


async def test_remaining_decreases():
    budget = CostBudget(max_budget_usd=1.0)
    assert budget.remaining == 1.0
    budget.record("gemini-2.5-flash", input_tokens=100_000, output_tokens=100_000)
    assert budget.remaining is not None
    assert budget.remaining < 1.0


async def test_summary():
    budget = CostBudget(max_budget_usd=10.0)
    budget.record("claude-sonnet-4-6", input_tokens=500, output_tokens=200, turn=1)
    budget.record("claude-sonnet-4-6", input_tokens=300, output_tokens=100, turn=2)
    budget.record("gemini-2.5-flash", input_tokens=1000, output_tokens=500, turn=3)

    s = budget.summary()
    assert s["total_entries"] == 3
    assert s["max_budget_usd"] == 10.0
    assert "claude-sonnet-4-6" in s["per_model"]
    assert "gemini-2.5-flash" in s["per_model"]
    assert s["per_model"]["claude-sonnet-4-6"]["calls"] == 2
    assert s["per_model"]["gemini-2.5-flash"]["calls"] == 1


async def test_from_env_with_budget():
    with patch.dict(os.environ, {"BREADMIND_MAX_BUDGET_USD": "5.50"}):
        budget = CostBudget.from_env()
        assert budget.remaining == 5.50


async def test_from_env_without_budget():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("BREADMIND_MAX_BUDGET_USD", None)
        budget = CostBudget.from_env()
        assert budget.remaining is None


async def test_entries_property():
    budget = CostBudget()
    budget.record("grok-3", input_tokens=100, output_tokens=50, turn=1)
    entries = budget.entries
    assert len(entries) == 1
    assert entries[0].model == "grok-3"
    # Returned list is a copy
    entries.clear()
    assert len(budget.entries) == 1
