# src/breadmind/messenger/service/message_service.py
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from breadmind.messenger.errors import NotFound, ValidationFailed, Forbidden
from breadmind.messenger.ts_seq import next_ts_seq, format_slack_ts
from breadmind.messenger.service.outbox_service import enqueue_outbox


@dataclass(frozen=True, slots=True)
class MessageRow:
    id: UUID
    workspace_id: UUID
    channel_id: UUID
    author_id: UUID
    parent_id: UUID | None
    kind: str
    text: str | None
    blocks: list
    created_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None
    ts_seq: int


_COLS = ("id, workspace_id, channel_id, author_id, parent_id, kind, text, blocks, "
         "created_at, edited_at, deleted_at, ts_seq")


async def post_message(
    db, *, workspace_id: UUID, channel_id: UUID,
    author_id: UUID, text: str | None = None, blocks: list | None = None,
    parent_id: UUID | None = None, client_msg_id: UUID | None = None,
    kind: str = "text",
) -> MessageRow:
    if not text and not blocks:
        raise ValidationFailed([{"field": "text|blocks", "msg": "at least one required"}])
    blocks = blocks or []
    mid = uuid4()
    async with db.transaction():
        seq = await next_ts_seq(db, channel_id)
        row = await db.fetchrow(
            f"""INSERT INTO messages
                  (id, workspace_id, channel_id, author_id, parent_id, kind, text, blocks,
                   client_msg_id, ts_seq)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
               RETURNING {_COLS}""",
            mid, workspace_id, channel_id, author_id, parent_id, kind,
            text, json.dumps(blocks), client_msg_id, seq,
        )
        await db.execute(
            "UPDATE channels SET last_message_at = $1 WHERE id = $2",
            row["created_at"], channel_id,
        )
        await enqueue_outbox(
            db, workspace_id=workspace_id, channel_id=channel_id,
            event_type="message.created",
            payload={
                "message_id": str(mid),
                "channel_id": str(channel_id),
                "author_id": str(author_id),
                "kind": kind,
                "ts": format_slack_ts(row["created_at"], seq),
            },
        )
    return _row_to_message(row)


async def get_message(db, *, channel_id: UUID, message_id: UUID) -> MessageRow:
    row = await db.fetchrow(
        f"SELECT {_COLS} FROM messages WHERE id = $1 AND channel_id = $2",
        message_id, channel_id,
    )
    if row is None:
        raise NotFound("message", str(message_id))
    return _row_to_message(row)


async def edit_message(
    db, *, channel_id: UUID, message_id: UUID,
    text: str | None = None, blocks: list | None = None, edited_by: UUID,
) -> MessageRow:
    async with db.transaction():
        prev = await db.fetchrow(
            "SELECT text, blocks, deleted_at, workspace_id FROM messages "
            "WHERE id = $1 AND channel_id = $2",
            message_id, channel_id,
        )
        if prev is None:
            raise NotFound("message", str(message_id))
        if prev["deleted_at"] is not None:
            raise Forbidden("cannot edit deleted message")
        await db.execute(
            "INSERT INTO message_edits (message_id, edited_at, prev_text, prev_blocks, edited_by) "
            "VALUES ($1, now(), $2, $3, $4)",
            message_id, prev["text"], prev["blocks"], edited_by,
        )
        updates = []
        args: list = []
        if text is not None:
            args.append(text)
            updates.append(f"text = ${len(args)}")
        if blocks is not None:
            args.append(json.dumps(blocks))
            updates.append(f"blocks = ${len(args)}::jsonb")
        if updates:
            args.append(message_id)
            await db.execute(
                f"UPDATE messages SET {', '.join(updates)}, edited_at = now() "
                f"WHERE id = ${len(args)}",
                *args,
            )
        await enqueue_outbox(
            db, workspace_id=prev["workspace_id"],
            channel_id=channel_id, event_type="message.updated",
            payload={"message_id": str(message_id), "channel_id": str(channel_id)},
        )
    return await get_message(db, channel_id=channel_id, message_id=message_id)


async def delete_message(db, *, channel_id: UUID, message_id: UUID) -> None:
    async with db.transaction():
        row = await db.fetchrow(
            "SELECT deleted_at, workspace_id FROM messages WHERE id = $1 AND channel_id = $2",
            message_id, channel_id,
        )
        if row is None:
            raise NotFound("message", str(message_id))
        if row["deleted_at"] is not None:
            return
        await db.execute(
            "UPDATE messages SET deleted_at = now() WHERE id = $1", message_id,
        )
        await enqueue_outbox(
            db, workspace_id=row["workspace_id"], channel_id=channel_id,
            event_type="message.deleted",
            payload={"message_id": str(message_id), "channel_id": str(channel_id)},
        )


async def list_messages(
    db, *, channel_id: UUID,
    before: datetime | None = None, after: datetime | None = None,
    limit: int = 50,
) -> tuple[list[MessageRow], bool]:
    where = ["channel_id = $1", "deleted_at IS NULL", "parent_id IS NULL"]
    args: list = [channel_id]
    if before:
        args.append(before)
        where.append(f"created_at < ${len(args)}")
    if after:
        args.append(after)
        where.append(f"created_at > ${len(args)}")
    args.append(limit + 1)
    rows = await db.fetch(
        f"SELECT {_COLS} FROM messages WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT ${len(args)}",
        *args,
    )
    has_more = len(rows) > limit
    return [_row_to_message(r) for r in rows[:limit]], has_more


async def list_thread_replies(
    db, *, channel_id: UUID, parent_id: UUID,
    limit: int = 50,
) -> tuple[list[MessageRow], bool]:
    args: list = [channel_id, parent_id, limit + 1]
    rows = await db.fetch(
        f"SELECT {_COLS} FROM messages "
        f"WHERE channel_id = $1 AND parent_id = $2 AND deleted_at IS NULL "
        f"ORDER BY created_at ASC LIMIT $3",
        *args,
    )
    has_more = len(rows) > limit
    return [_row_to_message(r) for r in rows[:limit]], has_more


def _row_to_message(row) -> MessageRow:
    d = dict(row)
    if isinstance(d.get("blocks"), str):
        d["blocks"] = json.loads(d["blocks"])
    return MessageRow(**d)
