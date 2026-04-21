"""Unit tests for ``ConnectorConfigsStore`` CRUD helpers.

Uses a record/playback fake DB — no real postgres required — so the
coverage for the SQL-shaped branches in ``configs_store.py`` is exercised
without standing up a container.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from breadmind.kb.connectors.configs_store import (
    ConnectorConfigRow,
    ConnectorConfigsStore,
)


class _FakeDB:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetch_return: list[dict] = []
        self.fetchrow_return: dict | None = None

    async def fetch(self, sql: str, *args: Any):
        self.fetch_calls.append((sql, args))
        return list(self.fetch_return)

    async def fetchrow(self, sql: str, *args: Any):
        self.fetchrow_calls.append((sql, args))
        return self.fetchrow_return

    async def execute(self, sql: str, *args: Any):
        self.execute_calls.append((sql, args))


async def test_list_no_filters_returns_all_rows():
    db = _FakeDB()
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db.fetch_return = [{
        "id": rid,
        "connector": "confluence",
        "project_id": pid,
        "scope_key": "SPACE",
        "settings": {"base_url": "https://x"},
        "enabled": True,
    }]
    store = ConnectorConfigsStore(db)
    rows = await store.list()
    assert len(rows) == 1
    assert isinstance(rows[0], ConnectorConfigRow)
    assert rows[0].id == rid
    assert rows[0].connector == "confluence"
    assert rows[0].settings == {"base_url": "https://x"}
    # No WHERE clause when no filters.
    sql, args = db.fetch_calls[0]
    assert "WHERE" not in sql
    assert args == ()


async def test_list_with_connector_filter_adds_where_clause():
    db = _FakeDB()
    db.fetch_return = []
    store = ConnectorConfigsStore(db)
    await store.list(connector="confluence")
    sql, args = db.fetch_calls[0]
    assert "WHERE" in sql
    assert "connector = $1" in sql
    assert args == ("confluence",)


async def test_list_enabled_only_adds_enabled_predicate():
    db = _FakeDB()
    db.fetch_return = []
    store = ConnectorConfigsStore(db)
    await store.list(connector="confluence", enabled_only=True)
    sql, _ = db.fetch_calls[0]
    assert "enabled = true" in sql
    assert "connector = $1" in sql


async def test_list_parses_settings_string_as_json():
    """When asyncpg returns jsonb as str, the store json.loads it."""
    db = _FakeDB()
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db.fetch_return = [{
        "id": rid,
        "connector": "confluence",
        "project_id": pid,
        "scope_key": "S",
        "settings": json.dumps({"base_url": "https://y"}),
        "enabled": False,
    }]
    store = ConnectorConfigsStore(db)
    rows = await store.list()
    assert rows[0].settings == {"base_url": "https://y"}
    assert rows[0].enabled is False


async def test_list_handles_none_settings_defaults_to_empty_dict():
    db = _FakeDB()
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db.fetch_return = [{
        "id": rid,
        "connector": "confluence",
        "project_id": pid,
        "scope_key": "S",
        "settings": None,
        "enabled": True,
    }]
    store = ConnectorConfigsStore(db)
    rows = await store.list()
    assert rows[0].settings == {}


async def test_register_upserts_row_and_returns_config_row():
    db = _FakeDB()
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db.fetchrow_return = {
        "id": rid,
        "connector": "confluence",
        "project_id": pid,
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    }
    store = ConnectorConfigsStore(db)
    row = await store.register(
        connector="confluence",
        project_id=pid,
        scope_key="PILOT",
        settings={"base_url": "https://x", "credentials_ref": "c:p"},
        enabled=True,
    )
    assert row.id == rid
    sql, args = db.fetchrow_calls[0]
    assert "INSERT INTO connector_configs" in sql
    assert "ON CONFLICT (connector, scope_key) DO UPDATE" in sql
    assert args[0] == "confluence"
    assert args[1] == pid
    assert args[2] == "PILOT"
    # settings is serialized as json for ::jsonb binding
    assert json.loads(args[3]) == {
        "base_url": "https://x", "credentials_ref": "c:p",
    }
    assert args[4] is True


async def test_set_enabled_issues_update_statement():
    db = _FakeDB()
    store = ConnectorConfigsStore(db)
    cid = uuid.uuid4()
    await store.set_enabled(cid, False)
    sql, args = db.execute_calls[0]
    assert "UPDATE connector_configs SET enabled" in sql
    assert args == (False, cid)


async def test_delete_issues_delete_statement():
    db = _FakeDB()
    store = ConnectorConfigsStore(db)
    cid = uuid.uuid4()
    await store.delete(cid)
    sql, args = db.execute_calls[0]
    assert "DELETE FROM connector_configs" in sql
    assert args == (cid,)
