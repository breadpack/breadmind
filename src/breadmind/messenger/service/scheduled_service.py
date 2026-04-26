# src/breadmind/messenger/service/scheduled_service.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from breadmind.messenger.errors import NotFound, ValidationFailed


@dataclass(frozen=True, slots=True)
class ScheduledMessageRow:
    id: UUID
    workspace_id: UUID
    channel_id: UUID
    author_id: UUID
    text: Optional[str]
    blocks: list
    scheduled_for: datetime
    created_at: datetime
    sent_message_id: Optional[UUID]
    cancelled_at: Optional[datetime]


_COLS = (
    "id, workspace_id, channel_id, author_id, text, blocks, "
    "scheduled_for, created_at, sent_message_id, cancelled_at"
)


def _row_to_scheduled(row) -> ScheduledMessageRow:
    import json
    d = dict(row)
    if isinstance(d.get("blocks"), str):
        d["blocks"] = json.loads(d["blocks"])
    d.setdefault("blocks", [])
    return ScheduledMessageRow(**d)


async def schedule_message(
    db, *,
    workspace_id: UUID,
    channel_id: UUID,
    author_id: UUID,
    text: Optional[str] = None,
    blocks: Optional[list] = None,
    scheduled_for: datetime,
) -> ScheduledMessageRow:
    if scheduled_for <= datetime.now(timezone.utc):
        raise ValidationFailed([{
            "field": "scheduled_for",
            "msg": "must be in the future",
        }])
    import json
    blocks = blocks or []
    sid = uuid4()
    row = await db.fetchrow(
        f"""INSERT INTO scheduled_messages
               (id, workspace_id, channel_id, author_id, text, blocks, scheduled_for)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            RETURNING {_COLS}""",
        sid, workspace_id, channel_id, author_id,
        text, json.dumps(blocks), scheduled_for,
    )
    return _row_to_scheduled(row)


async def list_scheduled(
    db, *, workspace_id: UUID, user_id: UUID,
) -> list[ScheduledMessageRow]:
    """Returns caller's own pending (not sent, not cancelled) scheduled messages."""
    rows = await db.fetch(
        f"SELECT {_COLS} FROM scheduled_messages "
        f"WHERE workspace_id = $1 AND author_id = $2 "
        f"AND sent_message_id IS NULL AND cancelled_at IS NULL "
        f"ORDER BY scheduled_for ASC",
        workspace_id, user_id,
    )
    return [_row_to_scheduled(r) for r in rows]


async def cancel_scheduled(
    db, *, scheduled_id: UUID, user_id: UUID,
) -> None:
    """Owner-only cancel. Raises NotFound if message doesn't exist or belongs to another user."""
    row = await db.fetchrow(
        "SELECT author_id, cancelled_at FROM scheduled_messages WHERE id = $1",
        scheduled_id,
    )
    if row is None or row["author_id"] != user_id:
        raise NotFound("scheduled_message", str(scheduled_id))
    if row["cancelled_at"] is not None:
        # Already cancelled — idempotent
        return
    await db.execute(
        "UPDATE scheduled_messages SET cancelled_at = now() WHERE id = $1",
        scheduled_id,
    )
