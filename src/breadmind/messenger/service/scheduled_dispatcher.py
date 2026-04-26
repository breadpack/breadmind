# src/breadmind/messenger/service/scheduled_dispatcher.py
"""
Scheduled message dispatcher.

This module provides `dispatch_due_messages`, a pure async function that finds
due scheduled messages and posts them via `post_message`.

It is designed to be called from a cron job (Arq, K8s CronJob, etc.) every
minute. Arq integration is intentionally omitted from this implementation
(deferred to a separate follow-up task) — Arq is not in the project's
current dependencies.
"""
from __future__ import annotations
import json

from breadmind.messenger.service.message_service import post_message


async def dispatch_due_messages(db) -> int:
    """Find due scheduled messages and post them. Returns count dispatched.

    Designed to be called from a cron job (Arq, K8s CronJob, etc.) every minute.
    NOTE: Arq worker integration is deferred — call this function directly from
    whatever scheduler is in use.
    """
    due_rows = await db.fetch(
        "SELECT id, workspace_id, channel_id, author_id, text, blocks "
        "FROM scheduled_messages "
        "WHERE scheduled_for <= now() AND sent_message_id IS NULL AND cancelled_at IS NULL "
        "ORDER BY scheduled_for "
        "LIMIT 100",
    )
    count = 0
    for row in due_rows:
        blocks = row["blocks"]
        if isinstance(blocks, str):
            blocks = json.loads(blocks)
        msg = await post_message(
            db,
            workspace_id=row["workspace_id"],
            channel_id=row["channel_id"],
            author_id=row["author_id"],
            text=row["text"],
            blocks=blocks,
        )
        await db.execute(
            "UPDATE scheduled_messages SET sent_message_id = $1 WHERE id = $2",
            msg.id, row["id"],
        )
        count += 1
    return count
