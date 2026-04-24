import pytest
from unittest.mock import MagicMock
from breadmind.web.deps import CurrentUser, get_current_user


def _fake_request(token: str | None = None):
    req = MagicMock()
    req.cookies = {"breadmind_session": token} if token else {}
    req.headers = {}
    return req


def test_dev_mode_when_auth_disabled(monkeypatch):
    import breadmind.web.deps as deps
    deps._auth = MagicMock(enabled=False)
    cu = get_current_user(_fake_request())
    assert cu == CurrentUser(username="local", is_admin=True)


def test_admin_env_recognized(monkeypatch):
    import breadmind.web.deps as deps
    auth = MagicMock(enabled=True)
    auth.get_session_username.return_value = "alice"
    deps._auth = auth
    monkeypatch.setenv("BREADMIND_ADMIN_USERS", "alice,bob")
    cu = get_current_user(_fake_request("tok"))
    assert cu.username == "alice"
    assert cu.is_admin is True


def test_non_admin_user(monkeypatch):
    import breadmind.web.deps as deps
    auth = MagicMock(enabled=True)
    auth.get_session_username.return_value = "carol"
    deps._auth = auth
    monkeypatch.setenv("BREADMIND_ADMIN_USERS", "alice,bob")
    cu = get_current_user(_fake_request("tok"))
    assert cu.username == "carol"
    assert cu.is_admin is False


def test_missing_token_raises(monkeypatch):
    import breadmind.web.deps as deps
    auth = MagicMock(enabled=True)
    deps._auth = auth
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        get_current_user(_fake_request())
    assert ei.value.status_code == 401
