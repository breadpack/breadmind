"""Integration Hub API tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from breadmind.web.routes.integrations import router
    app = FastAPI()
    app.include_router(router)

    oauth_mgr = AsyncMock()
    oauth_mgr.get_credentials = AsyncMock(return_value=None)
    oauth_mgr.revoke = AsyncMock()
    app.state.oauth_manager = oauth_mgr
    app.state.adapter_registry = MagicMock()
    app.state.adapter_registry.list_adapters = MagicMock(return_value=[])
    app.state.db = AsyncMock()
    app.state.db.get_setting = AsyncMock(return_value=None)
    app.state.db.set_setting = AsyncMock()

    return TestClient(app)


def test_list_all_services(client):
    resp = client.get("/api/integrations/services")
    assert resp.status_code == 200
    services = resp.json()
    assert len(services) > 10
    assert all("id" in s and "connected" in s for s in services)


def test_list_services_by_category(client):
    resp = client.get("/api/integrations/services?category=productivity")
    assert resp.status_code == 200
    services = resp.json()
    assert all(s["category"] == "productivity" for s in services)


def test_get_service_status(client):
    resp = client.get("/api/integrations/services/google_calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "google_calendar"
    assert data["auth_type"] == "oauth"


def test_get_unknown_service(client):
    resp = client.get("/api/integrations/services/unknown")
    assert resp.status_code == 404


def test_disconnect_service(client):
    resp = client.delete("/api/integrations/services/google_calendar/disconnect")
    assert resp.status_code == 200
    assert resp.json()["disconnected"] is True


def test_summary(client):
    resp = client.get("/api/integrations/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "connected" in data
    assert "categories" in data
