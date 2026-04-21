"""Connector admin routes CRUD tests.

Write endpoints (POST/PATCH/DELETE) are guarded by an
``x-admin-token`` header matched against ``BREADMIND_ADMIN_TOKEN`` —
tests install a dummy token via ``monkeypatch.setenv`` and pass it
through ``_ADMIN_HEADERS``.

NOTE: ``_build_store``/``_reload_beat`` are still monkeypatched directly
rather than using ``app.dependency_overrides`` because they are plain
module-level callables, not FastAPI ``Depends``-compatible providers.
Migrating them is tracked as a P5-carryover minor item — see the P5
handoff memo.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breadmind.web.routes.connectors import setup_connectors_routes

_ADMIN_TOKEN = "test-admin-token-value"
_ADMIN_HEADERS = {"x-admin-token": _ADMIN_TOKEN}


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
def app_with_routes(monkeypatch):
    monkeypatch.setenv("BREADMIND_ADMIN_TOKEN", _ADMIN_TOKEN)
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
    resp = client.post("/api/connectors", json=payload, headers=_ADMIN_HEADERS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["scope_key"] == "PILOT"
    assert state.reload_called == 1

    resp2 = client.get("/api/connectors")
    assert len(resp2.json()["configs"]) == 1


def test_pause_sets_enabled_false(app_with_routes):
    app, state = app_with_routes
    client = TestClient(app)
    client.post("/api/connectors", headers=_ADMIN_HEADERS, json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    })
    cid = state.store.rows[0]["id"]
    resp = client.patch(
        f"/api/connectors/{cid}",
        headers=_ADMIN_HEADERS,
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert state.store.rows[0]["enabled"] is False
    assert state.reload_called == 2


def test_delete_removes_row(app_with_routes):
    app, state = app_with_routes
    client = TestClient(app)
    client.post("/api/connectors", headers=_ADMIN_HEADERS, json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    })
    cid = state.store.rows[0]["id"]
    resp = client.delete(f"/api/connectors/{cid}", headers=_ADMIN_HEADERS)
    assert resp.status_code == 204
    assert state.store.rows == []


def test_register_rejects_missing_credentials_ref(app_with_routes):
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.post("/api/connectors", headers=_ADMIN_HEADERS, json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x"},
        "enabled": True,
    })
    assert resp.status_code == 400
    assert "credentials_ref" in resp.json()["detail"]


def test_register_rejects_non_https_base_url(app_with_routes):
    """TLS is required for Confluence — plain ``http://`` must 400."""
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.post("/api/connectors", headers=_ADMIN_HEADERS, json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {
            "base_url": "http://insecure.example.com/wiki",
            "credentials_ref": "confluence:pilot",
        },
        "enabled": True,
    })
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"].lower()


# ── Admin auth guard ──────────────────────────────────────────────────


def test_write_endpoint_without_token_returns_401(app_with_routes):
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.post("/api/connectors", json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
        "enabled": True,
    })
    assert resp.status_code == 401


def test_write_endpoint_with_wrong_token_returns_401(app_with_routes):
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.post(
        "/api/connectors",
        headers={"x-admin-token": "not-the-right-token"},
        json={
            "connector": "confluence",
            "project_id": "00000000-0000-4000-8000-000000000001",
            "scope_key": "PILOT",
            "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
            "enabled": True,
        },
    )
    assert resp.status_code == 401


def test_write_endpoint_without_env_returns_503(monkeypatch):
    """When BREADMIND_ADMIN_TOKEN is unset, write endpoints must 503 rather
    than silently accept any/no token."""
    monkeypatch.delenv("BREADMIND_ADMIN_TOKEN", raising=False)
    app = FastAPI()
    state = _StubAppState()
    app.state.app_state = state
    import breadmind.web.routes.connectors as conn_routes
    conn_routes._build_store = lambda db: state.store  # type: ignore[attr-defined]
    conn_routes._reload_beat = lambda db: state.reload_schedule()  # type: ignore[attr-defined]
    setup_connectors_routes(app, state)

    client = TestClient(app)
    resp = client.post(
        "/api/connectors",
        headers={"x-admin-token": "anything"},
        json={
            "connector": "confluence",
            "project_id": "00000000-0000-4000-8000-000000000001",
            "scope_key": "PILOT",
            "settings": {"base_url": "https://x", "credentials_ref": "c:p"},
            "enabled": True,
        },
    )
    assert resp.status_code == 503
    assert "BREADMIND_ADMIN_TOKEN" in resp.json()["detail"]


def test_list_endpoint_does_not_require_admin(app_with_routes):
    """GET is intentionally unguarded (read-only; no state change)."""
    app, _ = app_with_routes
    client = TestClient(app)
    resp = client.get("/api/connectors")
    assert resp.status_code == 200


# ── Beat reload resilience ────────────────────────────────────────────


def test_register_succeeds_even_if_beat_reload_fails(monkeypatch):
    """If Beat is down, the CRUD row is still persisted; we return 201
    (not 500) and let the next beat_init handler pick up the schedule."""
    monkeypatch.setenv("BREADMIND_ADMIN_TOKEN", _ADMIN_TOKEN)
    app = FastAPI()
    state = _StubAppState()
    app.state.app_state = state
    import breadmind.web.routes.connectors as conn_routes
    conn_routes._build_store = lambda db: state.store  # type: ignore[attr-defined]

    async def _broken_reload(db):
        raise RuntimeError("redis unreachable")

    conn_routes._reload_beat = _broken_reload  # type: ignore[attr-defined]
    setup_connectors_routes(app, state)

    client = TestClient(app)
    resp = client.post("/api/connectors", headers=_ADMIN_HEADERS, json={
        "connector": "confluence",
        "project_id": "00000000-0000-4000-8000-000000000001",
        "scope_key": "PILOT",
        "settings": {
            "base_url": "https://example.atlassian.net/wiki",
            "credentials_ref": "confluence:pilot",
        },
        "enabled": True,
    })
    assert resp.status_code == 201
    assert len(state.store.rows) == 1
