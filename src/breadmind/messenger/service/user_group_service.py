from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from breadmind.messenger.errors import NotFound, Conflict


@dataclass(frozen=True, slots=True)
class UserGroupRow:
    id: UUID
    workspace_id: UUID
    handle: str
    name: str
    description: str | None
    created_by: UUID | None
    created_at: datetime


_COLS = "id, workspace_id, handle, name, description, created_by, created_at"


async def list_groups(db, *, workspace_id: UUID) -> list[UserGroupRow]:
    rows = await db.fetch(
        f"SELECT {_COLS} FROM user_groups WHERE workspace_id = $1 ORDER BY created_at DESC",
        workspace_id,
    )
    return [UserGroupRow(**dict(r)) for r in rows]


async def get_group(db, *, workspace_id: UUID, group_id: UUID) -> UserGroupRow:
    row = await db.fetchrow(
        f"SELECT {_COLS} FROM user_groups WHERE id = $1 AND workspace_id = $2",
        group_id, workspace_id,
    )
    if row is None:
        raise NotFound("user_group", str(group_id))
    return UserGroupRow(**dict(row))


async def create_group(
    db, *,
    workspace_id: UUID,
    handle: str,
    name: str,
    description: str | None = None,
    created_by: UUID,
) -> UserGroupRow:
    gid = uuid4()
    try:
        row = await db.fetchrow(
            f"""INSERT INTO user_groups (id, workspace_id, handle, name, description, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING {_COLS}""",
            gid, workspace_id, handle, name, description, created_by,
        )
    except asyncpg.UniqueViolationError as e:
        raise Conflict(f"handle '{handle}' already exists in workspace") from e
    return UserGroupRow(**dict(row))


async def update_group(
    db, *,
    workspace_id: UUID,
    group_id: UUID,
    name: str | None = None,
    description: str | None = None,
    handle: str | None = None,
) -> UserGroupRow:
    updates = []
    args: list = []
    for field, val in [("name", name), ("description", description), ("handle", handle)]:
        if val is not None:
            args.append(val)
            updates.append(f"{field} = ${len(args)}")
    if updates:
        args.extend([group_id, workspace_id])
        try:
            await db.execute(
                f"UPDATE user_groups SET {', '.join(updates)} "
                f"WHERE id = ${len(args) - 1} AND workspace_id = ${len(args)}",
                *args,
            )
        except asyncpg.UniqueViolationError as e:
            raise Conflict(f"handle '{handle}' already exists in workspace") from e
    return await get_group(db, workspace_id=workspace_id, group_id=group_id)


async def delete_group(db, *, workspace_id: UUID, group_id: UUID) -> None:
    await db.execute(
        "DELETE FROM user_groups WHERE id = $1 AND workspace_id = $2",
        group_id, workspace_id,
    )


async def list_group_members(db, *, group_id: UUID) -> list[UUID]:
    rows = await db.fetch(
        "SELECT user_id FROM user_group_members WHERE group_id = $1",
        group_id,
    )
    return [row["user_id"] for row in rows]


async def set_group_members(db, *, group_id: UUID, user_ids: list[UUID]) -> None:
    await db.execute(
        "DELETE FROM user_group_members WHERE group_id = $1",
        group_id,
    )
    for uid in user_ids:
        await db.execute(
            "INSERT INTO user_group_members (group_id, user_id) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING",
            group_id, uid,
        )
