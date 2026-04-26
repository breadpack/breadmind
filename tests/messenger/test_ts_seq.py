"""Tests for per-channel monotonic ts_seq generator."""
from datetime import datetime, timezone
from uuid import uuid4
from breadmind.messenger.ts_seq import next_ts_seq, format_slack_ts, parse_slack_ts


async def test_next_ts_seq_monotonic_per_channel(test_db, seed_channel):
    _, cid, owner_id = seed_channel
    async with test_db.acquire() as conn:
        async with conn.transaction():
            a = await next_ts_seq(conn, cid)
            await conn.execute(
                "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
                "SELECT gen_random_uuid(), workspace_id, $1, $2, $3, 'm' FROM channels WHERE id = $1",
                cid, owner_id, a,
            )
            b = await next_ts_seq(conn, cid)
            await conn.execute(
                "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
                "SELECT gen_random_uuid(), workspace_id, $1, $2, $3, 'm' FROM channels WHERE id = $1",
                cid, owner_id, b,
            )
            c = await next_ts_seq(conn, cid)
    assert a < b < c
    assert a == 1 and b == 2 and c == 3


async def test_next_ts_seq_independent_per_channel(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    cid1 = uuid4()
    cid2 = uuid4()
    suffix = uuid4().hex[:8]
    async with test_db.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', $3)",
                cid1, wid, f"a-{suffix}",
            )
            await conn.execute(
                "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', $3)",
                cid2, wid, f"b-{suffix}",
            )
            a1 = await next_ts_seq(conn, cid1)
            await conn.execute(
                "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
                "VALUES (gen_random_uuid(), $1, $2, $3, $4, 'a1')",
                wid, cid1, owner_id, a1,
            )
            b1 = await next_ts_seq(conn, cid2)
            await conn.execute(
                "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
                "VALUES (gen_random_uuid(), $1, $2, $3, $4, 'b1')",
                wid, cid2, owner_id, b1,
            )
            a2 = await next_ts_seq(conn, cid1)
    assert a1 == 1 and b1 == 1 and a2 == 2


def test_format_slack_ts():
    dt = datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc)
    s = format_slack_ts(dt, 42)
    # Structural: ends with 6-digit zero-padded seq
    assert s.endswith(".000042")
    epoch, seq = parse_slack_ts(s)
    assert seq == 42
    assert epoch == int(dt.timestamp())


def test_parse_slack_ts_round_trip():
    dt = datetime(2026, 4, 26, 12, 30, 0, tzinfo=timezone.utc)
    s = format_slack_ts(dt, 999999)
    epoch, seq = parse_slack_ts(s)
    assert epoch == int(dt.timestamp())
    assert seq == 999999
