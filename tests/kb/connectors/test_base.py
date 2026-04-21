"""Unit tests for BaseConnector framework (no network)."""
from __future__ import annotations

import uuid
from typing import ClassVar

import pytest

from breadmind.kb.connectors.base import BaseConnector, SyncResult


class _FakeDB:
    def __init__(self):
        self.state: dict[tuple[str, str], dict] = {}

    async def fetchrow(self, sql: str, *args):
        connector, scope = args[0], args[1]
        row = self.state.get((connector, scope))
        return row

    async def execute(self, sql: str, *args):
        connector, scope = args[0], args[1]
        self.state[(connector, scope)] = {
            "connector": connector,
            "scope_key": scope,
            "project_id": args[2],
            "last_cursor": args[3],
            "last_run_at": args[4],
            "last_status": args[5],
            "last_error": args[6],
        }


def test_sync_result_is_dataclass_with_expected_fields():
    r = SyncResult(new_cursor="2026-04-20T01:00:00Z", processed=5, errors=1)
    assert r.new_cursor == "2026-04-20T01:00:00Z"
    assert r.processed == 5
    assert r.errors == 1


def test_base_connector_is_abstract():
    db = _FakeDB()
    with pytest.raises(TypeError):
        BaseConnector(db)  # type: ignore[abstract]


class _StubConnector(BaseConnector):
    connector_name: ClassVar[str] = "stub"

    def __init__(self, db, result: SyncResult):
        super().__init__(db)
        self._result = result

    async def _do_sync(self, project_id, scope_key, cursor):  # type: ignore[override]
        return self._result


async def test_sync_persists_cursor_and_status_ok():
    db = _FakeDB()
    project = uuid.uuid4()
    conn = _StubConnector(db, SyncResult(new_cursor="C2", processed=3, errors=0))

    result = await conn.sync(project, "spaceA", cursor=None)

    assert result == SyncResult(new_cursor="C2", processed=3, errors=0)
    row = db.state[("stub", "spaceA")]
    assert row["last_cursor"] == "C2"
    assert row["last_status"] == "ok"
    assert row["last_error"] is None
    assert row["project_id"] == project


async def test_sync_records_error_and_reraises():
    db = _FakeDB()

    class Boom(_StubConnector):
        async def _do_sync(self, project_id, scope_key, cursor):  # type: ignore[override]
            raise RuntimeError("kapow")

    conn = Boom(db, SyncResult(new_cursor="", processed=0, errors=0))
    with pytest.raises(RuntimeError, match="kapow"):
        await conn.sync(uuid.uuid4(), "spaceB", cursor="C0")

    row = db.state[("stub", "spaceB")]
    assert row["last_status"] == "error"
    assert "kapow" in row["last_error"]
    assert row["last_cursor"] == "C0"


async def test_load_cursor_reads_from_sync_state():
    db = _FakeDB()
    db.state[("stub", "spaceC")] = {
        "connector": "stub", "scope_key": "spaceC",
        "project_id": uuid.uuid4(), "last_cursor": "CURSOR-X",
        "last_run_at": None, "last_status": "ok", "last_error": None,
    }
    conn = _StubConnector(db, SyncResult(new_cursor="CURSOR-Y", processed=0, errors=0))
    got = await conn.load_cursor("spaceC")
    assert got == "CURSOR-X"


async def test_load_cursor_returns_none_when_missing():
    db = _FakeDB()
    conn = _StubConnector(db, SyncResult(new_cursor="", processed=0, errors=0))
    got = await conn.load_cursor("nope")
    assert got is None


# testcontainers Postgres integration — run only when Postgres is reachable.
async def test_connector_sync_state_upsert_against_real_postgres(test_db):
    """Uses the shared ``test_db`` fixture (applies alembic head) to verify
    that BaseConnector's sync_state upsert actually runs on a real DB."""
    from breadmind.kb.connectors.base import BaseConnector, SyncResult

    class _Real(BaseConnector):
        connector_name = "it_stub"

        async def _do_sync(self, project_id, scope_key, cursor):
            return SyncResult(new_cursor="C1", processed=1, errors=0)

    project_id = uuid.uuid4()
    async with test_db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO org_projects (id, name, slack_team_id) "
            "VALUES ($1, 'it', 'T1') ON CONFLICT DO NOTHING",
            project_id,
        )

    class _DBAdapter:
        def __init__(self, pool): self.pool = pool
        async def fetchrow(self, sql, *args):
            async with self.pool.acquire() as c:
                return await c.fetchrow(sql, *args)
        async def execute(self, sql, *args):
            async with self.pool.acquire() as c:
                return await c.execute(sql, *args)
        async def fetch(self, sql, *args):
            async with self.pool.acquire() as c:
                return await c.fetch(sql, *args)

    db = _DBAdapter(test_db._pool)
    conn = _Real(db)
    result = await conn.sync(project_id, "INT_SCOPE", cursor=None)
    assert result.new_cursor == "C1"
    loaded = await conn.load_cursor("INT_SCOPE")
    assert loaded == "C1"
