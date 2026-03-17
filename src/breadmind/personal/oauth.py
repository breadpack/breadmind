"""OAuth 2.0 credential manager for external service integrations.

Centralizes OAuth flows for Google, Microsoft, etc. Credentials are encrypted
and stored via the existing config_store/database pattern.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default scopes per provider
GOOGLE_SCOPES = {
    "calendar": ["https://www.googleapis.com/auth/calendar"],
    "drive": ["https://www.googleapis.com/auth/drive.readonly"],
    "contacts": ["https://www.googleapis.com/auth/contacts.readonly"],
}

MICROSOFT_SCOPES = {
    "calendar": ["Calendars.ReadWrite"],
    "files": ["Files.ReadWrite.All"],
    "contacts": ["Contacts.Read"],
}


@dataclass
class OAuthCredentials:
    """Stored OAuth credentials."""
    provider: str  # "google" | "microsoft"
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float = 0.0  # unix timestamp
    scopes: list[str] = field(default_factory=list)
    client_id: str = ""
    client_secret: str = ""

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60  # 60s buffer

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OAuthCredentials:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class OAuthManager:
    """Central OAuth 2.0 credential manager."""

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._credentials: dict[tuple[str, str], OAuthCredentials] = {}  # (provider, user_id) -> creds

    async def get_credentials(self, provider: str, user_id: str = "default") -> OAuthCredentials | None:
        """Get stored credentials. Returns None if not authenticated."""
        key = (provider, user_id)
        if key in self._credentials:
            creds = self._credentials[key]
            if creds.is_expired and creds.refresh_token:
                creds = await self._refresh_token(creds)
                self._credentials[key] = creds
                await self._save_credentials(provider, user_id, creds)
            return creds

        # Try loading from DB
        if self._db:
            creds = await self._load_credentials(provider, user_id)
            if creds:
                self._credentials[key] = creds
                return creds
        return None

    async def store_credentials(self, provider: str, user_id: str, creds: OAuthCredentials) -> None:
        """Store credentials in memory and database."""
        key = (provider, user_id)
        self._credentials[key] = creds
        await self._save_credentials(provider, user_id, creds)

    def get_auth_url(self, provider: str, scopes: list[str], redirect_uri: str,
                     client_id: str, state: str = "") -> str:
        """Generate OAuth authorization URL."""
        if provider == "google":
            base = "https://accounts.google.com/o/oauth2/v2/auth"
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "access_type": "offline",
                "prompt": "consent",
            }
            if state:
                params["state"] = state
            query = "&".join(f"{k}={v}" for k, v in params.items())
            return f"{base}?{query}"

        elif provider == "microsoft":
            base = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
            }
            if state:
                params["state"] = state
            query = "&".join(f"{k}={v}" for k, v in params.items())
            return f"{base}?{query}"

        raise ValueError(f"Unsupported provider: {provider}")

    async def exchange_code(self, provider: str, code: str, redirect_uri: str,
                           client_id: str, client_secret: str,
                           user_id: str = "default") -> OAuthCredentials:
        """Exchange authorization code for tokens."""
        import aiohttp

        if provider == "google":
            token_url = "https://oauth2.googleapis.com/token"
        elif provider == "microsoft":
            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data) as resp:
                result = await resp.json()

        if "error" in result:
            raise RuntimeError(f"OAuth token exchange failed: {result.get('error_description', result['error'])}")

        creds = OAuthCredentials(
            provider=provider,
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token"),
            token_type=result.get("token_type", "Bearer"),
            expires_at=time.time() + result.get("expires_in", 3600),
            scopes=result.get("scope", "").split(),
            client_id=client_id,
            client_secret=client_secret,
        )

        await self.store_credentials(provider, user_id, creds)
        return creds

    async def _refresh_token(self, creds: OAuthCredentials) -> OAuthCredentials:
        """Refresh an expired access token."""
        import aiohttp

        if creds.provider == "google":
            token_url = "https://oauth2.googleapis.com/token"
        elif creds.provider == "microsoft":
            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        else:
            return creds

        data = {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data) as resp:
                    result = await resp.json()

            if "error" in result:
                logger.error("Token refresh failed: %s", result.get("error_description"))
                return creds

            creds.access_token = result["access_token"]
            creds.expires_at = time.time() + result.get("expires_in", 3600)
            if "refresh_token" in result:
                creds.refresh_token = result["refresh_token"]
            logger.info("Token refreshed for %s", creds.provider)
        except Exception:
            logger.exception("Token refresh error")

        return creds

    async def _save_credentials(self, provider: str, user_id: str, creds: OAuthCredentials) -> None:
        if not self._db:
            return
        key = f"oauth:{provider}:{user_id}"
        await self._db.set_setting(key, json.dumps(creds.to_dict()))

    async def _load_credentials(self, provider: str, user_id: str) -> OAuthCredentials | None:
        if not self._db:
            return None
        key = f"oauth:{provider}:{user_id}"
        data = await self._db.get_setting(key)
        if data:
            return OAuthCredentials.from_dict(json.loads(data))
        return None

    async def revoke(self, provider: str, user_id: str = "default") -> bool:
        """Revoke credentials."""
        key = (provider, user_id)
        self._credentials.pop(key, None)
        if self._db:
            await self._db.set_setting(f"oauth:{provider}:{user_id}", None)
        return True
