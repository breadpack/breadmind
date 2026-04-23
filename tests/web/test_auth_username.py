from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from breadmind.web.app import WebApp
from breadmind.web.auth import AuthManager


def test_create_session_stores_username():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    token = am.create_session(ip="1.2.3.4", user_agent="UA", username="alice")
    assert am.get_session_username(token) == "alice"


def test_create_session_defaults_to_anonymous():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    token = am.create_session()
    assert am.get_session_username(token) == "anonymous"


def test_get_session_username_unknown_token():
    am = AuthManager(password_hash=AuthManager.hash_password("p"))
    assert am.get_session_username("no-such-token") is None


def test_login_accepts_username():
    """POST /api/auth/login with a username stores it on the session."""
    auth = AuthManager(password_hash=AuthManager.hash_password("correct-password"))
    app = WebApp(
        message_handler=AsyncMock(return_value="ok"),
        auth=auth,
    )
    client = TestClient(app.app)
    r = client.post(
        "/api/auth/login",
        json={"password": "correct-password", "username": "alice"},
    )
    assert r.status_code == 200
    token = r.cookies.get("breadmind_session")
    assert token
    # The session should have the username "alice" attached
    assert auth.get_session_username(token) == "alice"


def test_login_defaults_to_anonymous_when_username_missing():
    """POST /api/auth/login without username defaults the session to 'anonymous'."""
    auth = AuthManager(password_hash=AuthManager.hash_password("correct-password"))
    app = WebApp(
        message_handler=AsyncMock(return_value="ok"),
        auth=auth,
    )
    client = TestClient(app.app)
    r = client.post("/api/auth/login", json={"password": "correct-password"})
    assert r.status_code == 200
    token = r.cookies.get("breadmind_session")
    assert token
    assert auth.get_session_username(token) == "anonymous"
