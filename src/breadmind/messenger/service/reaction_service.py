# src/breadmind/messenger/service/reaction_service.py
from __future__ import annotations
from uuid import UUID

from breadmind.messenger.service.outbox_service import enqueue_outbox


async def add_reaction(db, *, message_id: UUID, user_id: UUID, emoji: str) -> None:
    row = await db.fetchrow(
        "SELECT workspace_id, channel_id FROM messages WHERE id = $1", message_id,
    )
    async with db.transaction():
        await db.execute(
            "INSERT INTO message_reactions (message_id, user_id, emoji) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            message_id, user_id, emoji,
        )
        if row:
            await enqueue_outbox(
                db,
                workspace_id=row["workspace_id"],
                channel_id=row["channel_id"],
                event_type="reaction.added",
                payload={
                    "message_id": str(message_id),
                    "user_id": str(user_id),
                    "emoji": emoji,
                },
            )


async def remove_reaction(db, *, message_id: UUID, user_id: UUID, emoji: str) -> None:
    row = await db.fetchrow(
        "SELECT workspace_id, channel_id FROM messages WHERE id = $1", message_id,
    )
    async with db.transaction():
        await db.execute(
            "DELETE FROM message_reactions WHERE message_id = $1 AND user_id = $2 AND emoji = $3",
            message_id, user_id, emoji,
        )
        if row:
            await enqueue_outbox(
                db,
                workspace_id=row["workspace_id"],
                channel_id=row["channel_id"],
                event_type="reaction.removed",
                payload={
                    "message_id": str(message_id),
                    "user_id": str(user_id),
                    "emoji": emoji,
                },
            )


async def list_reactions_for_message(
    db, *, message_id: UUID,
) -> list[dict]:
    rows = await db.fetch(
        "SELECT emoji, user_id FROM message_reactions WHERE message_id = $1 "
        "ORDER BY emoji, reacted_at",
        message_id,
    )
    grouped: dict[str, list[str]] = {}
    for row in rows:
        emoji = row["emoji"]
        uid = str(row["user_id"])
        grouped.setdefault(emoji, []).append(uid)

    return [
        {"emoji": emoji, "count": len(users), "users": users}
        for emoji, users in grouped.items()
    ]
