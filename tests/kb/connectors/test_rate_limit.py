"""Unit tests for HourlyPageBudget."""
from __future__ import annotations

import uuid

import pytest

from breadmind.kb.connectors.rate_limit import BudgetExceeded, HourlyPageBudget


async def test_allows_up_to_limit():
    budget = HourlyPageBudget(limit=3, now=lambda: 100.0)
    pid = uuid.uuid4()
    await budget.consume(pid, 1)
    await budget.consume(pid, 1)
    await budget.consume(pid, 1)


async def test_raises_when_exceeded():
    budget = HourlyPageBudget(limit=2, now=lambda: 100.0)
    pid = uuid.uuid4()
    await budget.consume(pid, 2)
    with pytest.raises(BudgetExceeded):
        await budget.consume(pid, 1)


async def test_window_rolls_over_after_one_hour():
    clock = {"t": 0.0}
    budget = HourlyPageBudget(limit=1, now=lambda: clock["t"])
    pid = uuid.uuid4()
    await budget.consume(pid, 1)
    clock["t"] = 3601.0
    await budget.consume(pid, 1)


async def test_projects_isolated():
    budget = HourlyPageBudget(limit=1, now=lambda: 100.0)
    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    await budget.consume(pid_a, 1)
    await budget.consume(pid_b, 1)
