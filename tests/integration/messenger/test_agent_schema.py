import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_agent_action_insert(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    agent_id = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name) "
        "VALUES ($1, $2, $3, 'agent', 'Bot')",
        agent_id, wid, f"agent-{suffix}@x.com",
    )
    mid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, kind) "
        "VALUES ($1, $2, $3, $4, 1, 'agent_action')", mid, wid, cid, agent_id,
    )
    aid = uuid4()
    await test_db.execute(
        "INSERT INTO agent_actions "
        "(id, workspace_id, message_id, agent_user_id, action_kind, tool_name) "
        "VALUES ($1, $2, $3, $4, 'tool_call', 'kb.query')",
        aid, wid, mid, agent_id,
    )
    row = await test_db.fetchrow("SELECT action_kind FROM agent_actions WHERE id = $1", aid)
    assert row["action_kind"] == "tool_call"


@pytest.mark.asyncio
async def test_agent_subscription_pk(test_db, seed_channel):
    wid, cid, _ = seed_channel
    agent_id = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name) "
        "VALUES ($1, $2, $3, 'agent', 'A')",
        agent_id, wid, f"sub-{suffix}@x.com",
    )
    await test_db.execute(
        "INSERT INTO agent_channel_subscriptions (channel_id, agent_user_id, trigger_mode) "
        "VALUES ($1, $2, 'mention')", cid, agent_id,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO agent_channel_subscriptions (channel_id, agent_user_id, trigger_mode) "
            "VALUES ($1, $2, 'always')", cid, agent_id,
        )


@pytest.mark.asyncio
async def test_episodic_note_source_message_fk(test_db, seed_channel):
    """episodic_notes에 source_message_id 컬럼이 추가되었는지 확인."""
    wid, cid, user_id = seed_channel
    cols = await test_db.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='episodic_notes' AND column_name IN ('source_message_id','source_channel_id')"
    )
    names = {r["column_name"] for r in cols}
    assert "source_message_id" in names
    assert "source_channel_id" in names


@pytest.mark.asyncio
async def test_audit_log_messenger_columns(test_db):
    cols = await test_db.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='audit_log' "
        "AND column_name IN ('actor_user_id','workspace_id','entity_kind','entity_id','action','payload')"
    )
    names = {r["column_name"] for r in cols}
    assert names >= {"actor_user_id", "workspace_id", "entity_kind", "entity_id", "action", "payload"}
