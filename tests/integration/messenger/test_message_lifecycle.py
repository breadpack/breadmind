import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_message_text_round_trip(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    mid = uuid4()
    await test_db.execute(
        """INSERT INTO messages
              (id, workspace_id, channel_id, author_id, kind, text, ts_seq)
           VALUES ($1, $2, $3, $4, 'text', 'hello', 1)""",
        mid, wid, cid, user_id,
    )
    row = await test_db.fetchrow(
        "SELECT kind, text, ts_seq, deleted_at FROM messages WHERE id = $1", mid,
    )
    assert row["kind"] == "text"
    assert row["text"] == "hello"
    assert row["ts_seq"] == 1
    assert row["deleted_at"] is None


@pytest.mark.asyncio
async def test_message_ts_seq_unique_per_channel(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq) "
        "VALUES (gen_random_uuid(), $1, $2, $3, 42)", wid, cid, user_id,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq) "
            "VALUES (gen_random_uuid(), $1, $2, $3, 42)", wid, cid, user_id,
        )


@pytest.mark.asyncio
async def test_message_thread_parent(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    parent_id = uuid4()
    reply_id = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'parent')", parent_id, wid, cid, user_id,
    )
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, parent_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, $5, 2, 'reply')",
        reply_id, wid, cid, user_id, parent_id,
    )
    rows = await test_db.fetch(
        "SELECT id FROM messages WHERE parent_id = $1 ORDER BY ts_seq", parent_id,
    )
    assert [r["id"] for r in rows] == [reply_id]


@pytest.mark.asyncio
async def test_reaction_pk(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    mid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq) "
        "VALUES ($1, $2, $3, $4, 1)", mid, wid, cid, user_id,
    )
    await test_db.execute(
        "INSERT INTO message_reactions (message_id, user_id, emoji) VALUES ($1, $2, ':+1:')",
        mid, user_id,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO message_reactions (message_id, user_id, emoji) VALUES ($1, $2, ':+1:')",
            mid, user_id,
        )


@pytest.mark.asyncio
async def test_outbox_insert_select_delete(test_db, seed_workspace):
    wid, _ = seed_workspace
    cid = uuid4()
    eid = uuid4()
    await test_db.execute(
        "INSERT INTO message_outbox (id, workspace_id, channel_id, event_type, payload, expires_at) "
        "VALUES ($1, $2, $3, 'message.created', '{}'::jsonb, now() + interval '60 seconds')",
        eid, wid, cid,
    )
    row = await test_db.fetchrow("SELECT event_type FROM message_outbox WHERE id = $1", eid)
    assert row["event_type"] == "message.created"
    await test_db.execute("DELETE FROM message_outbox WHERE id = $1", eid)
    assert await test_db.fetchrow("SELECT 1 FROM message_outbox WHERE id = $1", eid) is None
