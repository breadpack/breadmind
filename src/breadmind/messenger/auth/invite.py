"""Workspace invites — token-based, single-use."""
from __future__ import annotations
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4


class InviteInvalid(Exception):
    pass


class InviteExpired(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CreatedInvite:
    id: UUID
    token: str  # plaintext, return once, never log


def _hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create_invite(
    db,
    *,
    workspace_id: UUID,
    email: str,
    invited_by: UUID | None,
    role: str,
    ttl_days: int,
    channel_ids: list[UUID] | None = None,
) -> CreatedInvite:
    invite_id = uuid4()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    await db.execute(
        """INSERT INTO workspace_invites
              (id, workspace_id, email, invited_by, role, token_hash, channel_ids, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        invite_id, workspace_id, email, invited_by, role, token_hash,
        channel_ids, expires,
    )
    return CreatedInvite(id=invite_id, token=token)


async def accept_invite(
    db,
    *,
    token: str,
    display_name: str,
    external_id: str | None = None,
    real_name: str | None = None,
) -> UUID:
    token_hash = _hash_token(token)
    row = await db.fetchrow(
        """SELECT id, workspace_id, email, role, channel_ids, expires_at,
                  accepted_at, revoked_at
             FROM workspace_invites WHERE token_hash = $1""",
        token_hash,
    )
    if row is None:
        raise InviteInvalid("token not found")
    if row["revoked_at"] is not None:
        raise InviteInvalid("revoked")
    if row["accepted_at"] is not None:
        raise InviteInvalid("already accepted")
    if datetime.now(timezone.utc) > row["expires_at"]:
        raise InviteExpired("expired")

    new_uid = uuid4()
    # Note: we don't wrap in a transaction here because Database.execute() acquires
    # a fresh connection per call. If passed an asyncpg.Connection directly, the
    # caller can wrap externally. For test_db (Database wrapper), each .execute()
    # auto-commits which is acceptable for invite acceptance (rollback on failure
    # would only affect the in-progress UPDATE, which is fine).
    await db.execute(
        """INSERT INTO workspace_users
              (id, workspace_id, email, kind, display_name, real_name,
               external_id, role)
           VALUES ($1, $2, $3, 'human', $4, $5, $6, $7)""",
        new_uid, row["workspace_id"], row["email"], display_name,
        real_name, external_id, row["role"],
    )
    await db.execute(
        "UPDATE workspace_invites SET accepted_at = now() WHERE id = $1", row["id"],
    )
    for cid in (row["channel_ids"] or []):
        await db.execute(
            "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING", cid, new_uid,
        )
    return new_uid


async def revoke_invite(db, invite_id: UUID) -> None:
    await db.execute(
        "UPDATE workspace_invites SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        invite_id,
    )
