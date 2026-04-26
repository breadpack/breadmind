"""Tests for src/breadmind/memory/runtime.py — org_id resolver and Slack lookup."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.memory.runtime import (
    _coerce_uuid,
    _lookup_org_id_by_slack_team,
    _parse_env_uuid,
    _resolve_org_id,
    clear_org_lookup_cache,
)


# ---------------------------------------------------------------------------
# Autouse fixture: clear cache between every test to prevent bleed
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    clear_org_lookup_cache()
    yield
    clear_org_lookup_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(row):
    """Build a mock db whose acquire() is an async context manager returning conn."""
    conn = AsyncMock()
    conn.fetchrow.return_value = row
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = None
    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)
    return db, conn


# ---------------------------------------------------------------------------
# Family 1: _resolve_org_id 4-step fallback
# ---------------------------------------------------------------------------

_ORG_A = uuid.uuid4()
_ORG_B = uuid.uuid4()
_ORG_ENV = uuid.uuid4()


@pytest.mark.parametrize(
    "explicit, ctx_org_id, env_default, expected_type",
    [
        # (a) explicit wins over everything
        (_ORG_A, _ORG_B, _ORG_ENV, _ORG_A),
        # (b) ctx wins when no explicit
        (None, _ORG_B, _ORG_ENV, _ORG_B),
        # (c) env wins when neither explicit nor ctx
        (None, None, _ORG_ENV, _ORG_ENV),
        # (d) None when nothing
        (None, None, None, None),
    ],
    ids=["explicit-wins", "ctx-wins", "env-wins", "all-none"],
)
def test_resolve_org_id_fallback(explicit, ctx_org_id, env_default, expected_type):
    result = _resolve_org_id(
        explicit=explicit,
        ctx_org_id=ctx_org_id,
        env_default=env_default,
    )
    assert result == expected_type


def test_resolve_org_id_reads_env_by_default(monkeypatch):
    """When env_default is omitted, it should read BREADMIND_DEFAULT_ORG_ID from env."""
    env_id = uuid.uuid4()
    monkeypatch.setenv("BREADMIND_DEFAULT_ORG_ID", str(env_id))
    result = _resolve_org_id()
    assert result == env_id


def test_resolve_org_id_no_env_returns_none(monkeypatch):
    monkeypatch.delenv("BREADMIND_DEFAULT_ORG_ID", raising=False)
    assert _resolve_org_id() is None


def test_resolve_org_id_invalid_env_returns_none(monkeypatch):
    """When BREADMIND_DEFAULT_ORG_ID is invalid, resolver returns None
    (going through _parse_env_uuid, which warns and returns None)."""
    monkeypatch.setenv("BREADMIND_DEFAULT_ORG_ID", "not-a-uuid")
    assert _resolve_org_id() is None


def test_resolve_org_id_str_explicit_normalized():
    """String UUID inputs should be coerced."""
    org = uuid.uuid4()
    result = _resolve_org_id(explicit=str(org), env_default=None)
    assert result == org


# ---------------------------------------------------------------------------
# Family 2: _coerce_uuid
# ---------------------------------------------------------------------------

def test_coerce_uuid_passes_uuid_through():
    uid = uuid.uuid4()
    assert _coerce_uuid(uid) is uid


def test_coerce_uuid_parses_valid_string():
    uid = uuid.uuid4()
    result = _coerce_uuid(str(uid))
    assert result == uid
    assert isinstance(result, uuid.UUID)


def test_coerce_uuid_returns_none_on_invalid_string():
    assert _coerce_uuid("not-a-uuid") is None


def test_coerce_uuid_returns_none_on_none():
    assert _coerce_uuid(None) is None


# ---------------------------------------------------------------------------
# Family 3: _parse_env_uuid
# ---------------------------------------------------------------------------

def test_parse_env_uuid_valid(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setenv("TEST_ORG_UUID", str(uid))
    assert _parse_env_uuid("TEST_ORG_UUID") == uid


def test_parse_env_uuid_missing_var(monkeypatch):
    monkeypatch.delenv("TEST_ORG_UUID", raising=False)
    assert _parse_env_uuid("TEST_ORG_UUID") is None


def test_parse_env_uuid_invalid_emits_warning(monkeypatch, caplog):
    monkeypatch.setenv("TEST_ORG_UUID", "INVALID_VALUE")
    import logging
    with caplog.at_level(logging.WARNING, logger="breadmind.memory.runtime"):
        result = _parse_env_uuid("TEST_ORG_UUID")
    assert result is None
    # Verify warning was emitted at WARNING level
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1
    assert "TEST_ORG_UUID" in warnings[0].message


# ---------------------------------------------------------------------------
# Family 4: _lookup_org_id_by_slack_team cache hit/miss
# ---------------------------------------------------------------------------

async def test_lookup_cache_hit_db_called_once():
    """Two lookups for the same team_id → DB fetchrow called only once."""
    org_id = uuid.uuid4()
    db, conn = _make_db({"id": org_id})

    result1 = await _lookup_org_id_by_slack_team("T_TEAM_1", db)
    result2 = await _lookup_org_id_by_slack_team("T_TEAM_1", db)

    assert result1 == org_id
    assert result2 == org_id
    conn.fetchrow.assert_awaited_once()


async def test_lookup_cache_miss_cached_as_none():
    """Miss path (fetchrow returns None) → cached as None → second call skips DB."""
    db, conn = _make_db(None)

    result1 = await _lookup_org_id_by_slack_team("T_MISSING", db)
    result2 = await _lookup_org_id_by_slack_team("T_MISSING", db)

    assert result1 is None
    assert result2 is None
    conn.fetchrow.assert_awaited_once()


async def test_lookup_different_teams_hit_db_each():
    """Different team IDs each get their own DB call."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    db_a, conn_a = _make_db({"id": org_a})
    db_b, conn_b = _make_db({"id": org_b})

    r_a = await _lookup_org_id_by_slack_team("T_A", db_a)
    r_b = await _lookup_org_id_by_slack_team("T_B", db_b)

    assert r_a == org_a
    assert r_b == org_b
    conn_a.fetchrow.assert_awaited_once()
    conn_b.fetchrow.assert_awaited_once()


# ---------------------------------------------------------------------------
# Family 5: clear_org_lookup_cache
# ---------------------------------------------------------------------------

async def test_clear_cache_causes_db_hit_again():
    """After clear_org_lookup_cache(), the same team_id triggers a fresh DB call."""
    org_id = uuid.uuid4()
    db, conn = _make_db({"id": org_id})

    # First lookup — populates cache
    await _lookup_org_id_by_slack_team("T_CLEAR", db)
    assert conn.fetchrow.await_count == 1

    # Clear cache
    clear_org_lookup_cache()

    # Second lookup — should hit DB again
    result = await _lookup_org_id_by_slack_team("T_CLEAR", db)
    assert result == org_id
    assert conn.fetchrow.await_count == 2


async def test_clear_cache_is_idempotent():
    """Clearing an already-empty cache should not raise."""
    clear_org_lookup_cache()
    clear_org_lookup_cache()  # no error


async def test_concurrent_lookups_same_team_hit_db_once():
    """Double-checked locking ensures N concurrent first-access calls
    for the same team_id produce exactly ONE DB fetch."""
    import asyncio as _asyncio

    target = uuid.uuid4()
    db, conn = _make_db({"id": target})

    async def slow_fetchrow(*a, **kw):
        await _asyncio.sleep(0.01)
        return {"id": target}

    conn.fetchrow.side_effect = slow_fetchrow
    results = await _asyncio.gather(*[
        _lookup_org_id_by_slack_team("T_RACE", db) for _ in range(10)
    ])
    assert all(r == target for r in results)
    assert conn.fetchrow.await_count == 1
