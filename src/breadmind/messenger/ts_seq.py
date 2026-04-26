"""Per-channel monotonic ts_seq for Slack-compat 'ts' projection."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg


async def next_ts_seq(conn: asyncpg.Connection, channel_id: UUID) -> int:
    """Return next ts_seq for the given channel.

    Uses MAX(ts_seq) + 1 within a transaction, with row-level lock on the channel
    via SELECT ... FOR UPDATE on channels. Caller must be inside a transaction
    AND must INSERT a message with the returned ts_seq before the next call;
    otherwise the value will be reused (this function does not allocate, it
    only computes "next available").
    """
    await conn.execute(
        "SELECT 1 FROM channels WHERE id = $1 FOR UPDATE", channel_id,
    )
    row = await conn.fetchrow(
        "SELECT COALESCE(MAX(ts_seq), 0) + 1 AS next FROM messages WHERE channel_id = $1",
        channel_id,
    )
    return int(row["next"])


def format_slack_ts(created_at: datetime, ts_seq: int) -> str:
    """Slack-compat 'ts' format: '<epoch_seconds>.<6-digit-ts_seq>'."""
    epoch = int(created_at.timestamp())
    return f"{epoch}.{ts_seq:06d}"


def parse_slack_ts(ts: str) -> tuple[int, int]:
    """Inverse of format_slack_ts. Returns (epoch_seconds, ts_seq)."""
    epoch_str, seq_str = ts.split(".")
    return int(epoch_str), int(seq_str)
