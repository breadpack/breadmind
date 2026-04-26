"""020_messenger_m1_cleanup 마이그레이션 결과 검증.

후속 cleanup 3건의 실제 schema 효과를 head 적용 후 확인:
1. channel_members.notification_pref NOT NULL
2. messages.episodic_link integer / agent_actions.episodic_note_id integer
3. message_mentions broadcast(target_id NULL) INSERT 가능 + targeted UNIQUE
"""
from uuid import uuid4

import pytest


async def _column_type(db, table: str, column: str) -> str:
    row = await db.fetchrow(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2",
        table, column,
    )
    return row["data_type"]


# --- 1. notification_pref NOT NULL --------------------------------------------

async def test_notification_pref_not_null_on_channel_members(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', 'g')",
        cid, wid,
    )
    with pytest.raises(Exception, match="null value"):
        await test_db.execute(
            "INSERT INTO channel_members (channel_id, user_id, notification_pref) "
            "VALUES ($1, $2, NULL)",
            cid, owner_id,
        )


# --- 2. episodic_link / episodic_note_id integer ------------------------------

async def test_messages_episodic_link_is_integer(test_db):
    assert await _column_type(test_db, "messages", "episodic_link") == "integer"


async def test_agent_actions_episodic_note_id_is_integer(test_db):
    assert await _column_type(test_db, "agent_actions", "episodic_note_id") == "integer"


async def test_messages_episodic_link_fk_accepts_serial_id(test_db, seed_workspace):
    """episodic_notes.id (SERIAL=int4) 와 type 정확매칭 — INSERT 후 FK 정상 동작."""
    wid, owner_id = seed_workspace
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', 'g')",
        cid, wid,
    )
    note_id = await test_db.fetchrow(
        "INSERT INTO episodic_notes (content) VALUES ('hello') RETURNING id"
    )
    mid = uuid4()
    await test_db.execute(
        """INSERT INTO messages
           (id, workspace_id, channel_id, author_id, kind, text, ts_seq, episodic_link)
           VALUES ($1, $2, $3, $4, 'text', 'hi', 1, $5)""",
        mid, wid, cid, owner_id, note_id["id"],
    )
    row = await test_db.fetchrow(
        "SELECT episodic_link FROM messages WHERE id = $1", mid,
    )
    assert row["episodic_link"] == note_id["id"]


# --- 3. message_mentions PK 분리 ----------------------------------------------

async def _seed_message(db, wid, owner_id) -> tuple:
    cid = uuid4()
    await db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', 'g')",
        cid, wid,
    )
    mid = uuid4()
    await db.execute(
        """INSERT INTO messages
           (id, workspace_id, channel_id, author_id, kind, text, ts_seq)
           VALUES ($1, $2, $3, $4, 'text', 'hi', 1)""",
        mid, wid, cid, owner_id,
    )
    return cid, mid


async def test_mention_broadcast_here_inserts_with_null_target(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    _, mid = await _seed_message(test_db, wid, owner_id)
    await test_db.execute(
        "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
        "VALUES ($1, 'here', NULL)",
        mid,
    )
    # 동일 메시지의 'everyone'은 별도 mention_kind이므로 OK
    await test_db.execute(
        "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
        "VALUES ($1, 'everyone', NULL)",
        mid,
    )
    rows = await test_db.fetch(
        "SELECT mention_kind FROM message_mentions WHERE message_id = $1 ORDER BY mention_kind",
        mid,
    )
    assert [r["mention_kind"] for r in rows] == ["everyone", "here"]


async def test_mention_broadcast_uniqueness_per_kind(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    _, mid = await _seed_message(test_db, wid, owner_id)
    await test_db.execute(
        "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
        "VALUES ($1, 'here', NULL)",
        mid,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
            "VALUES ($1, 'here', NULL)",
            mid,
        )


async def test_mention_targeted_uniqueness_per_target(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    _, mid = await _seed_message(test_db, wid, owner_id)
    user_a = uuid4()
    user_b = uuid4()
    await test_db.execute(
        "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
        "VALUES ($1, 'user', $2)",
        mid, user_a,
    )
    # 다른 target_id는 OK
    await test_db.execute(
        "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
        "VALUES ($1, 'user', $2)",
        mid, user_b,
    )
    # 동일 target_id 중복은 위배
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO message_mentions (message_id, mention_kind, target_id) "
            "VALUES ($1, 'user', $2)",
            mid, user_a,
        )
