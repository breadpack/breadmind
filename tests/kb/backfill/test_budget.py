"""Tests for OrgMonthlyBudget — per-org monthly token ceiling (decision P1)."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from breadmind.kb.backfill.budget import (
    OrgMonthlyBudget,
    OrgMonthlyBudgetExceeded,
)


async def test_charge_first_time_creates_row(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    b = OrgMonthlyBudget(db=test_db, ceiling=1_000_000)
    remaining = await b.charge(org_id=org_id, tokens=100, period=date(2026, 4, 1))
    assert remaining == 999_900
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tokens_used, tokens_ceiling FROM kb_backfill_org_budget "
            "WHERE org_id=$1 AND period_month=$2",
            org_id,
            date(2026, 4, 1),
        )
        assert row["tokens_used"] == 100
        assert row["tokens_ceiling"] == 1_000_000


async def test_charge_accumulates_within_month(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    b = OrgMonthlyBudget(db=test_db, ceiling=1_000)
    await b.charge(org_id=org_id, tokens=400, period=date(2026, 4, 1))
    remaining = await b.charge(
        org_id=org_id, tokens=300, period=date(2026, 4, 1)
    )
    assert remaining == 300


async def test_charge_raises_when_exceeded(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    b = OrgMonthlyBudget(db=test_db, ceiling=500)
    await b.charge(org_id=org_id, tokens=400, period=date(2026, 4, 1))
    with pytest.raises(OrgMonthlyBudgetExceeded):
        await b.charge(org_id=org_id, tokens=200, period=date(2026, 4, 1))


async def test_remaining_returns_ceiling_when_no_row(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)
    b = OrgMonthlyBudget(db=test_db, ceiling=10_000)
    assert await b.remaining(org_id=org_id, period=date(2026, 4, 1)) == 10_000
