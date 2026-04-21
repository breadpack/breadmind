"""Connector admin routes CRUD tests (no auth context assumed for pilot)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breadmind.web.routes.connectors import setup_connectors_routes


class _StubStore:
    def __init__(self):
        self.rows: list[dict] = []

    async def list(self, connector=None, enabled_only=False):
        return [MagicMock(**r) for r in self.rows]

    async def register(self, *, connector, project_id, scope_key, settings, enabled=True):
        row = {
            "id": uuid.uuid4(),
            "connector": connector,
            "project_id": project_id,
            "scope_key": scope_key,
            "settings": settings,
            "enabled": enabled,
        }
        self.rows = [r for r in self.rows
                     if not (r["connector"] == connector and r["scope_key"] == scope_key)]
        self.rows.append(row)
        return MagicMock(**row)

    async def set_enabled(self, config_id, enabled):
        for r in self.rows:
            if r["id"] == config_id:
                r["enabled"] = enabled

    async def delete(self, config_id):
        self.rows = [r for r in self.rows if r["id"] != config_id]


class _StubAppState:
    def __init__(self):
        self._db = MagicMock()
        self._config = None
        self.store = _StubStore()
        self.reload_called = 0

    async def reload_schedule(self):
        self.reload_called += 1


@pytest.fixture
def app_with_routes():
    app = FastAPI()
    state = _StubAppState()
    app.state.app_state = state

    import breadmind.web.routes.connectors as conn_routes
    conn_routes._build_store = lambda db: state.store  # type: ignore[attr-defined]
    conn_routes._reload_beat = lambda db: state.reload_schedule()  # type: ignore[attr-defined]
    setup_connectors_routes(app, state)
    return app, state


def test_list_returns_registered_configs(app_with_routes):
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.get("/api/connectors")
    assert resp.status_code == 200
    assert resp.json() == {"configs": []}


def test_register_persists_and_reloads_schedule(app_with_routes):
    app, state = app_with_routes
    client = TestClient(app)
    payload = {
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {
            "base_url": "https://example.atlassian.net/wiki",
            "credentials_ref": "confluence:pilot",
        },
        "enabled": True,
    }
    resp = client.post("/api/connectors", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["scope_key"] == "PILOT"
    assert state.reload_called == 1

    resp2 = client.get("/api/connectors")
    assert len(resp2.json()["configs"]) == 1


def test_pause_sets_enabled_false(app_with_routes):
    app, state = app_with_routes
    client = TestClient(app)
    client.post("/api/connectors", json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    })
    cid = state.store.rows[0]["id"]
    resp = client.patch(f"/api/connectors/{cid}", json={"enabled": False})
    assert resp.status_code == 200
    assert state.store.rows[0]["enabled"] is False
    assert state.reload_called == 2


def test_delete_removes_row(app_with_routes):
    app, state = app_with_routes
    client = TestClient(app)
    client.post("/api/connectors", json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    })
    cid = state.store.rows[0]["id"]
    resp = client.delete(f"/api/connectors/{cid}")
    assert resp.status_code == 204
    assert state.store.rows == []


def test_register_rejects_missing_credentials_ref(app_with_routes):
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.post("/api/connectors", json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x"},
        "enabled": True,
    })
    assert resp.status_code == 400
    assert "credentials_ref" in resp.json()["detail"]
