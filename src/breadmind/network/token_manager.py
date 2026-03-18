"""Join Token management for worker provisioning.

Tokens authenticate new workers during initial registration.
After validation, a mTLS certificate is issued via PKIManager.
"""
from __future__ import annotations

import logging
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


@dataclass
class JoinToken:
    """A token that authorizes a new worker to join the network."""
    token_id: str
    secret: str  # base64url-encoded 32-byte random
    created_at: datetime
    expires_at: datetime
    max_uses: int = 1
    uses: int = 0
    created_by: str = ""
    labels: dict = field(default_factory=dict)  # auto-assigned role/tags
    revoked: bool = False

    @property
    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.uses >= self.max_uses:
            return False
        if datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "secret": self.secret,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "max_uses": self.max_uses,
            "uses": self.uses,
            "created_by": self.created_by,
            "labels": self.labels,
            "revoked": self.revoked,
            "is_valid": self.is_valid,
        }


class TokenManager:
    """Creates, validates, and manages join tokens."""

    def __init__(self, db=None, default_ttl_hours: int = 1, max_ttl_hours: int = 24):
        self._tokens: dict[str, JoinToken] = {}  # secret -> JoinToken
        self._by_id: dict[str, JoinToken] = {}   # token_id -> JoinToken
        self._db = db
        self._default_ttl = timedelta(hours=default_ttl_hours)
        self._max_ttl = timedelta(hours=max_ttl_hours)

    def create_token(
        self,
        ttl_hours: float | None = None,
        max_uses: int = 1,
        created_by: str = "",
        labels: dict | None = None,
    ) -> JoinToken:
        """Create a new join token."""
        now = datetime.now(timezone.utc)

        if ttl_hours is None:
            ttl = self._default_ttl
        else:
            ttl = timedelta(hours=min(ttl_hours, self._max_ttl.total_seconds() / 3600))

        token_id = secrets.token_hex(8)  # 16-char hex ID
        secret = urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

        token = JoinToken(
            token_id=token_id,
            secret=secret,
            created_at=now,
            expires_at=now + ttl,
            max_uses=max(1, max_uses),
            created_by=created_by,
            labels=labels or {},
        )

        self._tokens[secret] = token
        self._by_id[token_id] = token

        logger.info(
            "Join token created: id=%s, ttl=%s, max_uses=%d, by=%s",
            token_id, ttl, max_uses, created_by,
        )

        return token

    def validate_and_consume(self, secret: str) -> JoinToken | None:
        """Validate a token secret and consume one use.

        Returns the token if valid, None if invalid/expired/exhausted.
        """
        token = self._tokens.get(secret)
        if token is None:
            return None
        if not token.is_valid:
            return None

        token.uses += 1
        logger.info(
            "Join token consumed: id=%s, uses=%d/%d",
            token.token_id, token.uses, token.max_uses,
        )
        return token

    def peek(self, secret: str) -> JoinToken | None:
        """Check if a token is valid without consuming it."""
        token = self._tokens.get(secret)
        if token is None or not token.is_valid:
            return None
        return token

    def revoke(self, token_id: str) -> bool:
        """Revoke a token by ID."""
        token = self._by_id.get(token_id)
        if token is None:
            return False
        token.revoked = True
        logger.info("Join token revoked: id=%s", token_id)
        return True

    def list_tokens(self, include_expired: bool = False) -> list[dict]:
        """List all tokens."""
        result = []
        for token in self._by_id.values():
            if not include_expired and not token.is_valid:
                continue
            result.append(token.to_dict())
        return result

    def get_by_id(self, token_id: str) -> JoinToken | None:
        return self._by_id.get(token_id)

    def cleanup_expired(self) -> int:
        """Remove expired/exhausted tokens from memory."""
        now = datetime.now(timezone.utc)
        to_remove = []
        for secret, token in self._tokens.items():
            if token.revoked or now > token.expires_at or token.uses >= token.max_uses:
                to_remove.append(secret)

        for secret in to_remove:
            token = self._tokens.pop(secret)
            self._by_id.pop(token.token_id, None)

        return len(to_remove)

    async def save_to_db(self):
        """Persist active tokens to DB."""
        if not self._db:
            return
        try:
            tokens_data = [t.to_dict() for t in self._by_id.values() if t.is_valid]
            await self._db.set_setting("join_tokens", tokens_data)
        except Exception as e:
            logger.warning("Failed to save tokens: %s", e)

    async def load_from_db(self):
        """Load tokens from DB."""
        if not self._db:
            return
        try:
            data = await self._db.get_setting("join_tokens")
            if not data or not isinstance(data, list):
                return
            for d in data:
                token = JoinToken(
                    token_id=d["token_id"],
                    secret=d["secret"],
                    created_at=datetime.fromisoformat(d["created_at"]),
                    expires_at=datetime.fromisoformat(d["expires_at"]),
                    max_uses=d.get("max_uses", 1),
                    uses=d.get("uses", 0),
                    created_by=d.get("created_by", ""),
                    labels=d.get("labels", {}),
                    revoked=d.get("revoked", False),
                )
                if token.is_valid:
                    self._tokens[token.secret] = token
                    self._by_id[token.token_id] = token
        except Exception as e:
            logger.warning("Failed to load tokens: %s", e)
