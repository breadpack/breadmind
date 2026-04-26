"""Tests for HourlyPageBudget instance-keyed dimension (D5).

These tests verify the (project_id, instance_id) key extension that allows
a single project to run independent budgets per source instance — e.g., two
Slack workspaces under one BreadMind org.
"""
from __future__ import annotations

import uuid

import pytest

from breadmind.kb.connectors.rate_limit import (
    BudgetExceeded,
    HourlyPageBudget,
)


async def test_legacy_org_only_key_still_works():
    """Backwards compat: passing only project_id preserves existing behaviour."""
    b = HourlyPageBudget(limit=2)
    pid = uuid.uuid4()
    await b.consume(pid, count=1)
    await b.consume(pid, count=1)
    with pytest.raises(BudgetExceeded):
        await b.consume(pid, count=1)


async def test_instance_keyed_two_orgs_one_workspace_share_dim():
    b = HourlyPageBudget(limit=2)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    await b.consume(org_a, count=2, instance_id="T1")
    # Different org, same workspace — independent budgets.
    await b.consume(org_b, count=2, instance_id="T1")
    with pytest.raises(BudgetExceeded):
        await b.consume(org_a, count=1, instance_id="T1")


async def test_instance_keyed_one_org_two_workspaces_separate_budgets():
    b = HourlyPageBudget(limit=2)
    org = uuid.uuid4()
    await b.consume(org, count=2, instance_id="T1")
    # Same org, different workspace — independent budget.
    await b.consume(org, count=2, instance_id="T2")
    with pytest.raises(BudgetExceeded):
        await b.consume(org, count=1, instance_id="T1")
