import pytest
from uuid import uuid4
from breadmind.messenger.acl.message import can_user_see_message, can_user_edit_message


@pytest.mark.asyncio
async def test_see_message_inherits_channel(test_db, seed_channel):
    wid, cid, owner_id = seed_channel
    mid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'x')", mid, wid, cid, owner_id,
    )
    assert await can_user_see_message(test_db, user_id=owner_id, message_id=mid)


@pytest.mark.asyncio
async def test_edit_own_message(test_db, seed_channel):
    wid, cid, user_id = seed_channel
    mid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'x')", mid, wid, cid, user_id,
    )
    assert await can_user_edit_message(test_db, user_id=user_id, message_id=mid)


@pytest.mark.asyncio
async def test_cannot_edit_other_user_message(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', $3)",
        cid, wid, f"g-{suffix}",
    )
    other_id = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'O', 'member')",
        other_id, wid, f"o-{suffix}@x.com",
    )
    mid = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'x')", mid, wid, cid, other_id,
    )
    assert await can_user_edit_message(test_db, user_id=owner_id, message_id=mid)
    bystander_id = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'B', 'member')",
        bystander_id, wid, f"b-{suffix}@x.com",
    )
    assert not await can_user_edit_message(test_db, user_id=bystander_id, message_id=mid)
