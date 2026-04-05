"""Tests for API route versioning."""
from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from breadmind.web.app import WebApp
from breadmind.web.versioning import ACTIVE_VERSIONS, APIVersion, DEFAULT_VERSION


def _make_app(**kwargs) -> WebApp:
    """Create a minimal WebApp for testing."""
    return WebApp(
        message_handler=AsyncMock(return_value="test response"),
        **kwargs,
    )


class TestAPIVersionEnum:
    """Verify APIVersion enum values."""

    def test_v1_value(self):
        assert APIVersion.V1.value == "v1"

    def test_v2_value(self):
        assert APIVersion.V2.value == "v2"

    def test_v1_is_active(self):
        assert APIVersion.V1 in ACTIVE_VERSIONS

    def test_default_version_is_v1(self):
        assert DEFAULT_VERSION == APIVersion.V1


class TestVersionsEndpoint:
    """Test the /api/versions discovery endpoint."""

    def test_versions_endpoint(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/api/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert "v1" in data["versions"]
        assert data["default"] == "v1"


class TestV1RouteAccessible:
    """Test that /api/v1/... paths are correctly routed."""

    def test_v1_health_deep(self):
        """A known API route should be accessible via /api/v1/ prefix."""
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/api/v1/setup/status")
        # The endpoint may fail due to missing DB, but it should NOT be 404.
        # A 500 or actual response means routing worked.
        assert resp.status_code != 404

    def test_v1_config(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/api/v1/config")
        assert resp.status_code != 404


class TestLegacyRedirect:
    """Test that legacy /api/... paths redirect to /api/v1/..."""

    def test_legacy_redirect(self):
        app = _make_app()
        client = TestClient(app.app, follow_redirects=False)
        resp = client.get("/api/setup/status")
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "/api/v1/setup/status" in location

    def test_legacy_redirect_with_query(self):
        app = _make_app()
        client = TestClient(app.app, follow_redirects=False)
        resp = client.get("/api/config?foo=bar")
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "/api/v1/config" in location
        assert "foo=bar" in location

    def test_legacy_redirect_post(self):
        """POST to legacy path should also redirect with 307 (preserves method)."""
        app = _make_app()
        client = TestClient(app.app, follow_redirects=False)
        resp = client.post("/api/setup/validate", json={"provider": "test"})
        assert resp.status_code == 307

    def test_versions_endpoint_not_redirected(self):
        """/api/versions itself should NOT be redirected."""
        app = _make_app()
        client = TestClient(app.app, follow_redirects=False)
        resp = client.get("/api/versions")
        assert resp.status_code == 200


class TestHealthNotVersioned:
    """Test that /health remains accessible without version prefix."""

    def test_health_no_version(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_deep_no_version(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/health/deep")
        # May return 503 if no monitoring engine, but should not 404.
        assert resp.status_code != 404


class TestInvalidVersion:
    """Test that unsupported API versions return 404."""

    def test_unknown_version(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/api/v99/config")
        assert resp.status_code == 404
        assert "not available" in resp.json()["error"]
