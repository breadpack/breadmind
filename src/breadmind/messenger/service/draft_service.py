from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DraftRow:
    user_id: UUID
    channel_id: UUID
    thread_parent_id: Optional[UUID]
    text: Optional[str]
    blocks: list
    updated_at: datetime


async def upsert_draft(
    db, *, user_id: UUID, channel_id: UUID, thread_parent_id: UUID | None,
    text: str | None, blocks: list | None,
) -> None:
    # message_drafts has thread_key generated column; PK on (user_id, channel_id, thread_key).
    # Use thread_key for ON CONFLICT.
    await db.execute(
        """INSERT INTO message_drafts
              (user_id, channel_id, thread_parent_id, text, blocks, updated_at)
           VALUES ($1, $2, $3, $4, $5::jsonb, now())
           ON CONFLICT (user_id, channel_id, thread_key)
           DO UPDATE SET text = EXCLUDED.text, blocks = EXCLUDED.blocks, updated_at = now()""",
        user_id, channel_id, thread_parent_id,
        text, json.dumps(blocks or []),
    )


async def list_drafts(db, *, user_id: UUID, workspace_id: UUID) -> list[DraftRow]:
    rows = await db.fetch(
        """SELECT d.user_id, d.channel_id, d.thread_parent_id, d.text, d.blocks, d.updated_at
           FROM message_drafts d
           JOIN channels c ON c.id = d.channel_id
           WHERE d.user_id = $1 AND c.workspace_id = $2
           ORDER BY d.updated_at DESC""",
        user_id, workspace_id,
    )
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["blocks"], str):
            d["blocks"] = json.loads(d["blocks"])
        out.append(DraftRow(**d))
    return out


async def delete_draft(
    db, *, user_id: UUID, channel_id: UUID, thread_parent_id: UUID | None,
) -> None:
    if thread_parent_id is None:
        await db.execute(
            "DELETE FROM message_drafts WHERE user_id = $1 AND channel_id = $2 "
            "AND thread_parent_id IS NULL",
            user_id, channel_id,
        )
    else:
        await db.execute(
            "DELETE FROM message_drafts WHERE user_id = $1 AND channel_id = $2 "
            "AND thread_parent_id = $3",
            user_id, channel_id, thread_parent_id,
        )
