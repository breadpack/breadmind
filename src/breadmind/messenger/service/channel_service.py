from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from breadmind.messenger.errors import NotFound, Conflict, ValidationFailed


@dataclass(frozen=True, slots=True)
class ChannelRow:
    id: UUID
    workspace_id: UUID
    kind: str
    name: str | None
    topic: str | None
    purpose: str | None
    is_general: bool
    is_archived: bool
    posting_policy: str
    last_message_at: datetime | None
    created_at: datetime


_COLS = ("id, workspace_id, kind, name, topic, purpose, is_general, is_archived, "
         "posting_policy, last_message_at, created_at")


async def create_channel(
    db, *, workspace_id: UUID, kind: str, name: str,
    topic: str | None = None, purpose: str | None = None,
    created_by: UUID, initial_member_ids: list[UUID] | None = None,
) -> ChannelRow:
    if kind not in ("public", "private"):
        raise ValidationFailed([{"field": "kind", "msg": "must be public|private (DM/MPDM via /dms)"}])
    cid = uuid4()
    try:
        # Note: the Database wrapper doesn't expose .transaction(); we operate per-call.
        # If you have a real asyncpg.Connection, wrap in async with db.transaction().
        # For Database (test_db), each call auto-commits — atomicity within create_channel
        # is best-effort. The most likely failure is the membership INSERT, which would
        # leave an orphan channel; acceptable for V1.
        row = await db.fetchrow(
            f"""INSERT INTO channels
                   (id, workspace_id, kind, name, topic, purpose, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING {_COLS}""",
            cid, workspace_id, kind, name, topic, purpose, created_by,
        )
        await db.execute(
            "INSERT INTO channel_members (channel_id, user_id, role) "
            "VALUES ($1, $2, 'admin')", cid, created_by,
        )
        for uid in (initial_member_ids or []):
            if uid != created_by:
                await db.execute(
                    "INSERT INTO channel_members (channel_id, user_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING", cid, uid,
                )
    except asyncpg.UniqueViolationError as e:
        raise Conflict(f"channel name '{name}' already exists") from e
    return ChannelRow(**dict(row))


async def get_channel(db, *, workspace_id: UUID, channel_id: UUID) -> ChannelRow:
    row = await db.fetchrow(
        f"SELECT {_COLS} FROM channels WHERE id = $1 AND workspace_id = $2",
        channel_id, workspace_id,
    )
    if row is None:
        raise NotFound("channel", str(channel_id))
    return ChannelRow(**dict(row))


async def list_channels(
    db, *, workspace_id: UUID, kind: str | None = None,
    archived: bool = False, limit: int = 50,
) -> list[ChannelRow]:
    where = ["workspace_id = $1"]
    args: list = [workspace_id]
    if kind:
        args.append(kind)
        where.append(f"kind = ${len(args)}")
    if not archived:
        where.append("is_archived = false")
    args.append(limit)
    rows = await db.fetch(
        f"SELECT {_COLS} FROM channels WHERE {' AND '.join(where)} "
        f"ORDER BY last_message_at DESC NULLS LAST, created_at DESC LIMIT ${len(args)}",
        *args,
    )
    return [ChannelRow(**dict(r)) for r in rows]


async def update_channel(
    db, *, workspace_id: UUID, channel_id: UUID,
    name: str | None = None, topic: str | None = None, purpose: str | None = None,
    posting_policy: str | None = None,
) -> ChannelRow:
    updates = []
    args: list = []
    for field, val in [
        ("name", name), ("topic", topic), ("purpose", purpose), ("posting_policy", posting_policy),
    ]:
        if val is not None:
            args.append(val)
            updates.append(f"{field} = ${len(args)}")
    if updates:
        args.extend([channel_id, workspace_id])
        await db.execute(
            f"UPDATE channels SET {', '.join(updates)} "
            f"WHERE id = ${len(args)-1} AND workspace_id = ${len(args)}",
            *args,
        )
    return await get_channel(db, workspace_id=workspace_id, channel_id=channel_id)


async def archive_channel(db, *, workspace_id: UUID, channel_id: UUID) -> None:
    await db.execute(
        "UPDATE channels SET is_archived = true, archived_at = now() "
        "WHERE id = $1 AND workspace_id = $2",
        channel_id, workspace_id,
    )


async def add_members(db, *, channel_id: UUID, user_ids: list[UUID]) -> None:
    for uid in user_ids:
        await db.execute(
            "INSERT INTO channel_members (channel_id, user_id) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING", channel_id, uid,
        )


async def remove_member(db, *, channel_id: UUID, user_id: UUID) -> None:
    await db.execute(
        "DELETE FROM channel_members WHERE channel_id = $1 AND user_id = $2",
        channel_id, user_id,
    )
