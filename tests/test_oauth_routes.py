"""OAuth route tests using FastAPI TestClient."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from breadmind.web.routes.oauth import router

    app = FastAPI()
    app.include_router(router)

    # Mock app state
    oauth_mgr = AsyncMock()
    oauth_mgr.get_auth_url = MagicMock(return_value="https://accounts.google.com/auth?test=1")
    oauth_mgr.get_credentials = AsyncMock(return_value=None)
    oauth_mgr.revoke = AsyncMock(return_value=True)

    config = MagicMock()
    config.google_client_id = "test-client-id"
    config.google_client_secret = "test-secret"

    app.state.oauth_manager = oauth_mgr
    app.state.config = config

    return TestClient(app), oauth_mgr


def test_oauth_start_google(client):
    tc, mock_mgr = client
    resp = tc.get("/api/oauth/start/google?scopes=calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert data["provider"] == "google"


def test_oauth_start_invalid_provider(client):
    tc, _ = client
    resp = tc.get("/api/oauth/start/invalid")
    assert resp.status_code == 400


def test_oauth_status_not_authenticated(client):
    tc, _ = client
    resp = tc.get("/api/oauth/status/google")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


def test_oauth_revoke(client):
    tc, mock_mgr = client
    resp = tc.delete("/api/oauth/revoke/google")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    mock_mgr.revoke.assert_called_once_with("google")
