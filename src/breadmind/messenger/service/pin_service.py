# src/breadmind/messenger/service/pin_service.py
from __future__ import annotations
from uuid import UUID

from breadmind.messenger.service.message_service import MessageRow, _COLS, _row_to_message
from breadmind.messenger.service.outbox_service import enqueue_outbox


async def pin_message(
    db, *, channel_id: UUID, message_id: UUID, pinned_by: UUID,
) -> None:
    row = await db.fetchrow(
        "SELECT workspace_id FROM messages WHERE id = $1 AND channel_id = $2",
        message_id, channel_id,
    )
    async with db.transaction():
        await db.execute(
            "INSERT INTO message_pins (channel_id, message_id, pinned_by) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            channel_id, message_id, pinned_by,
        )
        if row:
            await enqueue_outbox(
                db,
                workspace_id=row["workspace_id"],
                channel_id=channel_id,
                event_type="pin.added",
                payload={
                    "message_id": str(message_id),
                    "channel_id": str(channel_id),
                    "pinned_by": str(pinned_by),
                },
            )


async def unpin_message(
    db, *, channel_id: UUID, message_id: UUID,
) -> None:
    row = await db.fetchrow(
        "SELECT workspace_id FROM messages WHERE id = $1 AND channel_id = $2",
        message_id, channel_id,
    )
    async with db.transaction():
        await db.execute(
            "DELETE FROM message_pins WHERE channel_id = $1 AND message_id = $2",
            channel_id, message_id,
        )
        if row:
            await enqueue_outbox(
                db,
                workspace_id=row["workspace_id"],
                channel_id=channel_id,
                event_type="pin.removed",
                payload={
                    "message_id": str(message_id),
                    "channel_id": str(channel_id),
                },
            )


async def list_pins(db, *, channel_id: UUID) -> list[MessageRow]:
    rows = await db.fetch(
        f"SELECT m.{', m.'.join(_COLS.split(', '))} "
        f"FROM message_pins mp "
        f"JOIN messages m ON m.id = mp.message_id "
        f"WHERE mp.channel_id = $1 AND m.deleted_at IS NULL "
        f"ORDER BY mp.pinned_at DESC",
        channel_id,
    )
    return [_row_to_message(r) for r in rows]
