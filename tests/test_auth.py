import time
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from breadmind.web.auth import AuthManager
from breadmind.web.app import WebApp
from breadmind.config import AppConfig, SecurityConfig


# --- AuthManager unit tests ---


class TestAuthManagerHashPassword:
    def test_hash_password_returns_sha256(self):
        result = AuthManager.hash_password("testpassword")
        assert len(result) == 64  # SHA-256 hex digest length
        assert result == AuthManager.hash_password("testpassword")  # deterministic

    def test_hash_password_different_inputs(self):
        h1 = AuthManager.hash_password("password1")
        h2 = AuthManager.hash_password("password2")
        assert h1 != h2


class TestAuthManagerVerifyPassword:
    def test_verify_password_correct(self):
        pw_hash = AuthManager.hash_password("correctpassword")
        auth = AuthManager(password_hash=pw_hash)
        assert auth.verify_password("correctpassword") is True

    def test_verify_password_wrong(self):
        pw_hash = AuthManager.hash_password("correctpassword")
        auth = AuthManager(password_hash=pw_hash)
        assert auth.verify_password("wrongpassword") is False


class TestAuthManagerSessions:
    def test_create_session_returns_token(self):
        auth = AuthManager(password_hash="somehash")
        token = auth.create_session(ip="127.0.0.1", user_agent="TestAgent")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_session_valid(self):
        auth = AuthManager(password_hash="somehash")
        token = auth.create_session()
        assert auth.verify_session(token) is True

    def test_verify_session_invalid(self):
        auth = AuthManager(password_hash="somehash")
        assert auth.verify_session("nonexistent-token") is False

    def test_verify_session_expired(self):
        auth = AuthManager(password_hash="somehash", session_timeout=1)
        token = auth.create_session()
        # Manually set created_at to the past
        auth._sessions[token]["created_at"] = time.time() - 2
        assert auth.verify_session(token) is False
        # Session should be removed
        assert token not in auth._sessions

    def test_revoke_session(self):
        auth = AuthManager(password_hash="somehash")
        token = auth.create_session()
        assert auth.verify_session(token) is True
        auth.revoke_session(token)
        assert auth.verify_session(token) is False

    def test_revoke_session_nonexistent(self):
        auth = AuthManager(password_hash="somehash")
        # Should not raise
        auth.revoke_session("nonexistent-token")


class TestAuthManagerApiKey:
    def test_verify_api_key_valid(self):
        auth = AuthManager(api_keys=["key1", "key2"])
        assert auth.verify_api_key("key1") is True
        assert auth.verify_api_key("key2") is True

    def test_verify_api_key_invalid(self):
        auth = AuthManager(api_keys=["key1"])
        assert auth.verify_api_key("wrongkey") is False

    def test_verify_api_key_empty(self):
        auth = AuthManager()
        assert auth.verify_api_key("anykey") is False


class TestAuthManagerEnabled:
    def test_enabled_with_password(self):
        auth = AuthManager(password_hash="somehash")
        assert auth.enabled is True

    def test_enabled_with_api_keys(self):
        auth = AuthManager(api_keys=["key1"])
        assert auth.enabled is True

    def test_disabled_by_default(self):
        auth = AuthManager()
        assert auth.enabled is False


class TestAuthManagerCleanup:
    def test_cleanup_expired(self):
        auth = AuthManager(password_hash="somehash", session_timeout=1)
        token1 = auth.create_session()
        token2 = auth.create_session()
        # Expire token1
        auth._sessions[token1]["created_at"] = time.time() - 2
        auth.cleanup_expired()
        assert token1 not in auth._sessions
        assert token2 in auth._sessions

    def test_get_active_sessions(self):
        auth = AuthManager(password_hash="somehash")
        auth.create_session()
        auth.create_session()
        assert auth.get_active_sessions() == 2


class TestAuthenticateRequest:
    def test_auth_disabled_always_passes(self):
        auth = AuthManager()  # disabled
        mock_request = MagicMock()
        assert auth.authenticate_request(mock_request) is True

    def test_authenticate_with_session_cookie(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        token = auth.create_session()
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "", "Authorization": ""}
        mock_request.cookies = {"breadmind_session": token}
        assert auth.authenticate_request(mock_request) is True

    def test_authenticate_with_api_key_header(self):
        auth = AuthManager(api_keys=["my-api-key"])
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "my-api-key", "Authorization": ""}
        mock_request.cookies = {}
        assert auth.authenticate_request(mock_request) is True

    def test_authenticate_with_bearer_token(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        token = auth.create_session()
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "", "Authorization": f"Bearer {token}"}
        mock_request.cookies = {}
        assert auth.authenticate_request(mock_request) is True

    def test_authenticate_fails_no_credentials(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "", "Authorization": ""}
        mock_request.cookies = {}
        assert auth.authenticate_request(mock_request) is False


class TestAuthenticateWebSocket:
    def test_auth_disabled_always_passes(self):
        auth = AuthManager()
        mock_ws = MagicMock()
        assert auth.authenticate_websocket(mock_ws) is True

    def test_authenticate_with_query_param(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        token = auth.create_session()
        mock_ws = MagicMock()
        mock_ws.query_params = {"token": token}
        mock_ws.cookies = {}
        assert auth.authenticate_websocket(mock_ws) is True

    def test_authenticate_with_cookie(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        token = auth.create_session()
        mock_ws = MagicMock()
        mock_ws.query_params = {}
        mock_ws.cookies = {"breadmind_session": token}
        assert auth.authenticate_websocket(mock_ws) is True

    def test_authenticate_fails_no_credentials(self):
        pw_hash = AuthManager.hash_password("password")
        auth = AuthManager(password_hash=pw_hash)
        mock_ws = MagicMock()
        mock_ws.query_params = {}
        mock_ws.cookies = {}
        assert auth.authenticate_websocket(mock_ws) is False


# --- Integration tests with FastAPI TestClient ---


def _make_auth():
    """Create an AuthManager with a known password."""
    pw_hash = AuthManager.hash_password("testpassword123")
    return AuthManager(password_hash=pw_hash, api_keys=["test-api-key-123"])


def _make_app(auth=None, **kwargs):
    """Create a WebApp with auth and a simple message handler."""
    return WebApp(
        message_handler=AsyncMock(return_value="test response"),
        auth=auth,
        **kwargs,
    )


class TestLoginEndpoint:
    def test_login_success(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/login", json={"password": "testpassword123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "token" in data
        # Should set cookie
        assert "breadmind_session" in resp.cookies

    def test_login_failure(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/login", json={"password": "wrongpassword"})
        assert resp.status_code == 401
        assert "error" in resp.json()

    def test_login_when_auth_disabled(self):
        auth = AuthManager()  # disabled
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/login", json={"password": ""})
        assert resp.status_code == 200
        assert resp.json()["message"] == "Auth disabled"


class TestLogoutEndpoint:
    def test_logout_clears_session(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        # Login first
        login_resp = client.post("/api/auth/login", json={"password": "testpassword123"})
        token = login_resp.json()["token"]
        assert auth.verify_session(token) is True
        # Logout
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert auth.verify_session(token) is False


class TestAuthStatusEndpoint:
    def test_status_auth_disabled(self):
        app = _make_app()
        client = TestClient(app.app)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is False
        assert data["authenticated"] is True

    def test_status_authenticated(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        # Login
        client.post("/api/auth/login", json={"password": "testpassword123"})
        # Check status (cookie is set automatically in TestClient)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is True
        assert data["authenticated"] is True

    def test_status_unauthenticated(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is True
        assert data["authenticated"] is False


class TestSetupAuthEndpoint:
    def test_setup_initial_password(self):
        auth = AuthManager()  # no password set
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/setup", json={"password": "newpassword123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert auth.enabled is True
        assert auth.verify_password("newpassword123") is True

    def test_setup_rejects_short_password(self):
        auth = AuthManager()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/setup", json={"password": "short"})
        assert resp.status_code == 400
        assert "at least 8" in resp.json()["error"]

    def test_setup_rejects_if_already_configured(self):
        auth = _make_auth()  # already has password
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        resp = client.post("/api/auth/setup", json={"password": "newpassword123"})
        assert resp.status_code == 403


class TestAuthMiddleware:
    def test_blocks_unauthenticated_api(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/api/tools")
        assert resp.status_code == 401
        assert resp.json()["error"] == "Authentication required"

    def test_allows_health_endpoint(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/health")
        # health endpoint returns 503 because no monitoring engine, but NOT 401
        assert resp.status_code in (200, 503)
        assert "error" not in resp.json() or resp.json().get("error") != "Authentication required"

    def test_allows_auth_endpoints(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        # /api/auth/status should be accessible without auth
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200

    def test_allows_webhook_receive(self):
        auth = _make_auth()
        # Create app without webhook manager so the endpoint returns 503
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        # The webhook receive path should bypass auth middleware
        resp = client.post("/api/webhook/receive/test", json={"data": "test"})
        # Should get 503 (webhook not configured), NOT 401 (auth required)
        assert resp.status_code == 503

    def test_allows_api_with_session_cookie(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app)
        # Login first
        client.post("/api/auth/login", json={"password": "testpassword123"})
        # Now API calls should work
        resp = client.get("/api/tools")
        assert resp.status_code == 200

    def test_allows_api_with_api_key_header(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/api/tools", headers={"X-API-Key": "test-api-key-123"})
        assert resp.status_code == 200

    def test_allows_api_with_bearer_token(self):
        auth = _make_auth()
        token = auth.create_session()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/api/tools", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_allows_index_without_auth(self):
        auth = _make_auth()
        app = _make_app(auth=auth)
        client = TestClient(app.app, cookies={})
        resp = client.get("/")
        # Index should be accessible (even if auth is enabled, the page itself loads)
        assert resp.status_code == 200

    def test_no_auth_means_all_pass(self):
        app = _make_app()  # no auth at all
        client = TestClient(app.app)
        resp = client.get("/api/tools")
        assert resp.status_code == 200


class TestCorsHeaders:
    def test_cors_headers_present(self):
        config = AppConfig()
        app = _make_app(config=config)
        client = TestClient(app.app)
        resp = client.options(
            "/api/tools",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8080"
        assert "access-control-allow-credentials" in resp.headers

    def test_cors_custom_origins(self):
        config = AppConfig(
            security=SecurityConfig(cors_origins=["https://custom.example.com"])
        )
        app = _make_app(config=config)
        client = TestClient(app.app)
        resp = client.options(
            "/api/tools",
            headers={
                "Origin": "https://custom.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://custom.example.com"


class TestSecurityConfig:
    def test_default_security_config(self):
        config = SecurityConfig()
        assert config.auth_enabled is False
        assert config.password_hash == ""
        assert config.api_keys == []
        assert config.session_timeout == 86400
        assert config.require_https is False
        assert "http://localhost:8080" in config.cors_origins

    def test_security_config_in_app_config(self):
        config = AppConfig()
        assert hasattr(config, 'security')
        assert isinstance(config.security, SecurityConfig)

    def test_web_config_default_host_is_localhost(self):
        from breadmind.config import WebConfig
        config = WebConfig()
        assert config.host == "127.0.0.1"
