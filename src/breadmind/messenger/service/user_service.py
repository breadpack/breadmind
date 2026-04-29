from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from uuid import UUID

from breadmind.messenger.errors import NotFound, ValidationFailed
from breadmind.messenger.service.audit_service import write_audit
from breadmind.messenger.acl.cache import VisibleChannelsCache
from breadmind.messenger.acl.realtime import publish_user_invalidate


@dataclass(frozen=True, slots=True)
class UserRow:
    id: UUID
    workspace_id: UUID
    external_id: str | None
    email: str
    kind: str
    display_name: str
    real_name: str | None
    avatar_url: str | None
    status_text: str | None
    status_emoji: str | None
    timezone: str | None
    locale: str
    role: str
    joined_at: datetime
    deactivated_at: datetime | None


_USER_COLS = (
    "id, workspace_id, external_id, email, kind, display_name, real_name, "
    "avatar_url, status_text, status_emoji, timezone, locale, role, joined_at, deactivated_at"
)


async def list_users(
    db, *, workspace_id: UUID,
    kind: str | None = None, active: bool = True,
    email: str | None = None, limit: int = 50,
) -> list[UserRow]:
    where = ["workspace_id = $1"]
    args: list = [workspace_id]
    if active:
        where.append("deactivated_at IS NULL")
    if kind:
        args.append(kind)
        where.append(f"kind = ${len(args)}")
    if email:
        args.append(email)
        where.append(f"email = ${len(args)}")
    args.append(limit)
    rows = await db.fetch(
        f"SELECT {_USER_COLS} FROM workspace_users WHERE {' AND '.join(where)} "
        f"ORDER BY joined_at LIMIT ${len(args)}", *args,
    )
    return [UserRow(**dict(r)) for r in rows]


async def get_user(db, *, workspace_id: UUID, user_id: UUID) -> UserRow:
    row = await db.fetchrow(
        f"SELECT {_USER_COLS} FROM workspace_users WHERE id = $1 AND workspace_id = $2",
        user_id, workspace_id,
    )
    if row is None:
        raise NotFound("user", str(user_id))
    return UserRow(**dict(row))


async def update_user_profile(
    db, *, workspace_id: UUID, user_id: UUID,
    display_name: str | None = None, real_name: str | None = None,
    avatar_url: str | None = None, status_text: str | None = None,
    status_emoji: str | None = None, timezone: str | None = None, locale: str | None = None,
) -> UserRow:
    updates = []
    args: list = []
    for field, val in [
        ("display_name", display_name), ("real_name", real_name),
        ("avatar_url", avatar_url), ("status_text", status_text),
        ("status_emoji", status_emoji), ("timezone", timezone), ("locale", locale),
    ]:
        if val is not None:
            args.append(val)
            updates.append(f"{field} = ${len(args)}")
    if updates:
        args.extend([user_id, workspace_id])
        await db.execute(
            f"UPDATE workspace_users SET {', '.join(updates)} "
            f"WHERE id = ${len(args)-1} AND workspace_id = ${len(args)}",
            *args,
        )
    return await get_user(db, workspace_id=workspace_id, user_id=user_id)


async def update_user_role(
    db, *, workspace_id: UUID, user_id: UUID, role: str,
    redis=None,
) -> UserRow:
    if role not in ("owner", "admin", "member", "guest", "single_channel_guest"):
        raise ValidationFailed([{"field": "role", "msg": "invalid"}])
    await db.execute(
        "UPDATE workspace_users SET role = $1 WHERE id = $2 AND workspace_id = $3",
        role, user_id, workspace_id,
    )
    await write_audit(
        db, workspace_id=workspace_id, entity_kind="user",
        action="role_change", entity_id=user_id, payload={"role": role},
    )
    if redis is not None:
        cache = VisibleChannelsCache(redis, ttl_sec=300)
        await cache.invalidate_user(user_id)
        await publish_user_invalidate(redis, user_id=user_id)
    return await get_user(db, workspace_id=workspace_id, user_id=user_id)


async def deactivate_user(db, *, workspace_id: UUID, user_id: UUID) -> None:
    await db.execute(
        "UPDATE workspace_users SET deactivated_at = now() "
        "WHERE id = $1 AND workspace_id = $2 AND deactivated_at IS NULL",
        user_id, workspace_id,
    )
    await write_audit(
        db, workspace_id=workspace_id, entity_kind="user",
        action="deactivate", entity_id=user_id,
    )
