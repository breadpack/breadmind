"""Tests for Database pool-proxy convenience methods.

Production code paths (``breadmind.kb.connectors.configs_store``,
``breadmind.kb.connectors.base``, ``breadmind.kb.connectors.confluence``,
``breadmind.kb.e2e_facades``) invoke ``self._db.fetch(...)``,
``self._db.fetchrow(...)``, ``self._db.fetchval(...)`` and
``self._db.execute(...)`` directly on the Database wrapper. asyncpg.Pool
exposes these as one-shot convenience methods; Database must expose the
same surface so those call sites work against the production wrapper and
not only the ``_FakeDB`` stubs used in unit tests.
"""
from __future__ import annotations


async def test_fetch_returns_rows_from_pool(test_db):
    rows = await test_db.fetch("SELECT 1 AS n UNION ALL SELECT 2 AS n ORDER BY n")
    assert [r["n"] for r in rows] == [1, 2]


async def test_fetchrow_returns_single_record(test_db):
    row = await test_db.fetchrow("SELECT 42 AS answer")
    assert row is not None
    assert row["answer"] == 42


async def test_fetchrow_returns_none_for_empty_result(test_db):
    row = await test_db.fetchrow("SELECT 1 WHERE FALSE")
    assert row is None


async def test_fetchval_returns_scalar(test_db):
    assert await test_db.fetchval("SELECT 7") == 7


async def test_fetchval_with_args_positional_substitution(test_db):
    assert await test_db.fetchval("SELECT $1::int + $2::int", 3, 4) == 7


async def test_execute_runs_statement(test_db):
    # CREATE / INSERT / DROP on a TEMP table exercises the execute path end-to-end.
    await test_db.execute(
        "CREATE TEMP TABLE _proxy_smoke (k TEXT PRIMARY KEY, v INT)"
    )
    await test_db.execute(
        "INSERT INTO _proxy_smoke(k, v) VALUES ($1, $2)", "a", 1,
    )
    row = await test_db.fetchrow("SELECT v FROM _proxy_smoke WHERE k = $1", "a")
    assert row is not None
    assert row["v"] == 1
    await test_db.execute("DROP TABLE _proxy_smoke")
