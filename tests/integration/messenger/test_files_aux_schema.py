import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta

@pytest.mark.asyncio
async def test_file_round_trip(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    fid = uuid4()
    await test_db.execute(
        """INSERT INTO files
              (id, workspace_id, uploader_id, filename, mime_type, size_bytes, storage_key)
           VALUES ($1, $2, $3, 'doc.pdf', 'application/pdf', 12345, 'wid/abc.pdf')""",
        fid, wid, owner_id,
    )
    row = await test_db.fetchrow(
        "SELECT filename, storage_backend FROM files WHERE id = $1", fid,
    )
    assert row["filename"] == "doc.pdf"
    assert row["storage_backend"] == "s3"  # default

@pytest.mark.asyncio
async def test_message_attachment(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    mid = uuid4()
    fid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'pic')", mid, wid, cid, user_id,
    )
    await test_db.execute(
        "INSERT INTO files (id, workspace_id, uploader_id, filename, mime_type, size_bytes, storage_key) "
        "VALUES ($1, $2, $3, 'a.png', 'image/png', 100, 'wid/a.png')", fid, wid, user_id,
    )
    await test_db.execute(
        "INSERT INTO message_attachments (message_id, file_id, position) VALUES ($1, $2, 0)",
        mid, fid,
    )
    rows = await test_db.fetch(
        "SELECT file_id FROM message_attachments WHERE message_id = $1", mid,
    )
    assert len(rows) == 1

@pytest.mark.asyncio
async def test_custom_emoji_alias_or_image_required(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    with pytest.raises(Exception, match="violates check constraint"):
        await test_db.execute(
            "INSERT INTO custom_emojis (workspace_id, name, created_by) VALUES ($1, 'noimg', $2)",
            wid, owner_id,
        )

@pytest.mark.asyncio
async def test_scheduled_message_due_index(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    sid = uuid4()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await test_db.execute(
        "INSERT INTO scheduled_messages (id, workspace_id, channel_id, author_id, text, scheduled_for) "
        "VALUES ($1, $2, $3, $4, 'later', $5)", sid, wid, cid, user_id, future,
    )
    rows = await test_db.fetch(
        "SELECT id FROM scheduled_messages WHERE sent_message_id IS NULL AND cancelled_at IS NULL",
    )
    assert any(r["id"] == sid for r in rows)

@pytest.mark.asyncio
async def test_read_cursor_upsert(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    await test_db.execute(
        "INSERT INTO channel_read_cursors (user_id, channel_id, last_read_at) "
        "VALUES ($1, $2, now())", user_id, cid,
    )
    await test_db.execute(
        "UPDATE channel_read_cursors SET unread_count = 5 WHERE user_id = $1 AND channel_id = $2",
        user_id, cid,
    )
    row = await test_db.fetchrow(
        "SELECT unread_count FROM channel_read_cursors WHERE user_id = $1 AND channel_id = $2",
        user_id, cid,
    )
    assert row["unread_count"] == 5
