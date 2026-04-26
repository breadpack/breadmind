from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BookmarkRow:
    user_id: UUID
    message_id: UUID
    saved_at: datetime
    reminder_at: Optional[datetime]


async def add_bookmark(
    db, *, user_id: UUID, message_id: UUID, reminder_at: datetime | None = None,
) -> None:
    await db.execute(
        "INSERT INTO bookmarks (user_id, message_id, reminder_at) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id, message_id) DO UPDATE SET reminder_at = EXCLUDED.reminder_at",
        user_id, message_id, reminder_at,
    )


async def list_bookmarks(
    db, *, user_id: UUID, workspace_id: UUID,
) -> list[BookmarkRow]:
    rows = await db.fetch(
        "SELECT b.user_id, b.message_id, b.saved_at, b.reminder_at "
        "FROM bookmarks b JOIN messages m ON m.id = b.message_id "
        "WHERE b.user_id = $1 AND m.workspace_id = $2 "
        "ORDER BY b.saved_at DESC",
        user_id, workspace_id,
    )
    return [BookmarkRow(**dict(r)) for r in rows]


async def remove_bookmark(db, *, user_id: UUID, message_id: UUID) -> None:
    await db.execute(
        "DELETE FROM bookmarks WHERE user_id = $1 AND message_id = $2",
        user_id, message_id,
    )
