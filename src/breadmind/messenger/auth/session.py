"""User sessions — refresh-token rotation."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from .paseto import encode_access_token, encode_refresh_token, decode_refresh_token, PasetoError


class SessionRevoked(Exception):
    pass


class RefreshTokenInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SessionTokens:
    session_id: UUID
    access_token: str
    refresh_token: str


def _hash_refresh(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create_session(
    db,
    paseto_key_hex: str,
    *,
    user_id: UUID,
    workspace_id: UUID,
    access_ttl_min: int,
    refresh_ttl_days: int,
    device_info: dict[str, Any] | None = None,
    ip: str | None = None,
) -> SessionTokens:
    sid = uuid4()
    refresh = encode_refresh_token(paseto_key_hex, session_id=sid, ttl_days=refresh_ttl_days)
    refresh_hash = _hash_refresh(refresh)
    role = await _user_role(db, user_id)
    access = encode_access_token(
        paseto_key_hex, workspace_id=workspace_id, user_id=user_id,
        role=role, ttl_min=access_ttl_min,
    )
    expires = await _refresh_expires(db, refresh_ttl_days)
    # device_info dict needs JSON encoding for asyncpg jsonb column
    await db.execute(
        """INSERT INTO user_sessions
              (id, user_id, workspace_id, refresh_token_hash, device_info, ip_address, expires_at)
           VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)""",
        sid, user_id, workspace_id, refresh_hash,
        json.dumps(device_info) if device_info is not None else None,
        ip, expires,
    )
    return SessionTokens(session_id=sid, access_token=access, refresh_token=refresh)


async def refresh_session(
    db,
    paseto_key_hex: str,
    *,
    refresh_token: str,
    access_ttl_min: int,
    refresh_ttl_days: int,
) -> SessionTokens:
    try:
        sid = decode_refresh_token(paseto_key_hex, refresh_token)
    except PasetoError as e:
        raise RefreshTokenInvalid(str(e)) from e
    row = await db.fetchrow(
        "SELECT user_id, workspace_id, revoked_at, refresh_token_hash, expires_at "
        "FROM user_sessions WHERE id = $1", sid,
    )
    if row is None:
        raise RefreshTokenInvalid("session not found")
    if row["revoked_at"] is not None:
        raise SessionRevoked()
    if row["refresh_token_hash"] != _hash_refresh(refresh_token):
        raise RefreshTokenInvalid("token mismatch (rotated already?)")

    new_refresh = encode_refresh_token(paseto_key_hex, session_id=sid, ttl_days=refresh_ttl_days)
    new_hash = _hash_refresh(new_refresh)
    role = await _user_role(db, row["user_id"])
    new_access = encode_access_token(
        paseto_key_hex, workspace_id=row["workspace_id"], user_id=row["user_id"],
        role=role, ttl_min=access_ttl_min,
    )
    new_expires = await _refresh_expires(db, refresh_ttl_days)
    await db.execute(
        "UPDATE user_sessions SET refresh_token_hash = $1, expires_at = $2, last_used_at = now() "
        "WHERE id = $3",
        new_hash, new_expires, sid,
    )
    return SessionTokens(session_id=sid, access_token=new_access, refresh_token=new_refresh)


async def revoke_session(db, session_id: UUID) -> None:
    await db.execute(
        "UPDATE user_sessions SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        session_id,
    )


async def _user_role(db, user_id: UUID) -> str:
    row = await db.fetchrow("SELECT role FROM workspace_users WHERE id = $1", user_id)
    if row is None:
        raise RefreshTokenInvalid("user not found")
    return row["role"]


async def _refresh_expires(db, refresh_ttl_days: int):
    row = await db.fetchrow(
        "SELECT now() + ($1 || ' days')::interval AS exp", str(refresh_ttl_days)
    )
    return row["exp"]
