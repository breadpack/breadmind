"""PASETO v4.local tokens for native auth."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from uuid import UUID
import json

import pyseto


class PasetoError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    workspace_id: UUID
    user_id: UUID
    role: str
    expires_at: datetime


def _key_from_hex(key_hex: str):
    raw = bytes.fromhex(key_hex)
    if len(raw) != 32:
        raise PasetoError("PASETO key must be 32 bytes (64 hex chars)")
    return pyseto.Key.new(version=4, purpose="local", key=raw)


def encode_access_token(
    key_hex: str, *, workspace_id: UUID, user_id: UUID, role: str, ttl_min: int,
) -> str:
    key = _key_from_hex(key_hex)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_min)
    payload = {
        "wid": str(workspace_id),
        "uid": str(user_id),
        "role": role,
        "exp": expires.isoformat(),
        "kind": "access",
    }
    token = pyseto.encode(key, json.dumps(payload).encode())
    return token.decode() if isinstance(token, bytes) else token


def decode_access_token(key_hex: str, token: str) -> AccessClaims:
    key = _key_from_hex(key_hex)
    try:
        decoded = pyseto.decode(key, token)
    except Exception as e:  # noqa: BLE001
        raise PasetoError(f"decode failed: {e}") from e
    payload = json.loads(decoded.payload)
    if payload.get("kind") != "access":
        raise PasetoError("not an access token")
    expires = datetime.fromisoformat(payload["exp"])
    if datetime.now(timezone.utc) > expires:
        raise PasetoError("token expired")
    return AccessClaims(
        workspace_id=UUID(payload["wid"]),
        user_id=UUID(payload["uid"]),
        role=payload["role"],
        expires_at=expires,
    )


def encode_refresh_token(key_hex: str, *, session_id: UUID, ttl_days: int) -> str:
    key = _key_from_hex(key_hex)
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    payload = {
        "sid": str(session_id),
        "exp": expires.isoformat(),
        "kind": "refresh",
    }
    token = pyseto.encode(key, json.dumps(payload).encode())
    return token.decode() if isinstance(token, bytes) else token


def decode_refresh_token(key_hex: str, token: str) -> UUID:
    key = _key_from_hex(key_hex)
    try:
        decoded = pyseto.decode(key, token)
    except Exception as e:  # noqa: BLE001
        raise PasetoError(f"decode failed: {e}") from e
    payload = json.loads(decoded.payload)
    if payload.get("kind") != "refresh":
        raise PasetoError("not a refresh token")
    expires = datetime.fromisoformat(payload["exp"])
    if datetime.now(timezone.utc) > expires:
        raise PasetoError("token expired")
    return UUID(payload["sid"])
