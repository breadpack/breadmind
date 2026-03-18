"""OAuthManager unit tests."""
import time
import pytest


def test_credentials_not_expired():
    from breadmind.personal.oauth import OAuthCredentials
    creds = OAuthCredentials(provider="google", access_token="tok",
        expires_at=time.time() + 3600)
    assert not creds.is_expired


def test_credentials_expired():
    from breadmind.personal.oauth import OAuthCredentials
    creds = OAuthCredentials(provider="google", access_token="tok",
        expires_at=time.time() - 100)
    assert creds.is_expired


def test_credentials_serialization():
    from breadmind.personal.oauth import OAuthCredentials
    creds = OAuthCredentials(provider="google", access_token="tok",
        refresh_token="ref", scopes=["calendar"])
    d = creds.to_dict()
    restored = OAuthCredentials.from_dict(d)
    assert restored.provider == "google"
    assert restored.access_token == "tok"
    assert restored.refresh_token == "ref"


def test_google_auth_url():
    from breadmind.personal.oauth import OAuthManager
    mgr = OAuthManager()
    url = mgr.get_auth_url("google", ["https://www.googleapis.com/auth/calendar"],
        "http://localhost:8080/callback", "client123")
    assert "accounts.google.com" in url
    assert "client123" in url
    assert "calendar" in url


def test_microsoft_auth_url():
    from breadmind.personal.oauth import OAuthManager
    mgr = OAuthManager()
    url = mgr.get_auth_url("microsoft", ["Calendars.ReadWrite"],
        "http://localhost:8080/callback", "client456")
    assert "login.microsoftonline.com" in url


@pytest.mark.asyncio
async def test_get_credentials_returns_none_when_empty():
    from breadmind.personal.oauth import OAuthManager
    mgr = OAuthManager()
    result = await mgr.get_credentials("google")
    assert result is None


@pytest.mark.asyncio
async def test_store_and_get_credentials():
    from breadmind.personal.oauth import OAuthManager, OAuthCredentials
    mgr = OAuthManager()
    creds = OAuthCredentials(provider="google", access_token="tok",
        expires_at=time.time() + 3600)
    await mgr.store_credentials("google", "alice", creds)
    result = await mgr.get_credentials("google", "alice")
    assert result is not None
    assert result.access_token == "tok"


@pytest.mark.asyncio
async def test_revoke_credentials():
    from breadmind.personal.oauth import OAuthManager, OAuthCredentials
    mgr = OAuthManager()
    creds = OAuthCredentials(provider="google", access_token="tok",
        expires_at=time.time() + 3600)
    await mgr.store_credentials("google", "alice", creds)
    await mgr.revoke("google", "alice")
    result = await mgr.get_credentials("google", "alice")
    assert result is None
