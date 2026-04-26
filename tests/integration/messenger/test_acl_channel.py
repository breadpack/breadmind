import pytest
from uuid import uuid4
from breadmind.messenger.acl.channel import (
    can_user_see_channel, can_user_post_message,
)


@pytest.mark.asyncio
async def test_member_sees_public(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', $3)",
        cid, wid, f"g-{suffix}",
    )
    member_id = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'M', 'member')",
        member_id, wid, f"m-{suffix}@x.com",
    )
    assert await can_user_see_channel(test_db, user_id=member_id, channel_id=cid)


@pytest.mark.asyncio
async def test_guest_sees_public_only_if_member(test_db, seed_workspace):
    wid, _ = seed_workspace
    suffix = uuid4().hex[:8]
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', $3)",
        cid, wid, f"g-{suffix}",
    )
    guest_id = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'G', 'guest')",
        guest_id, wid, f"g-{suffix}@x.com",
    )
    assert not await can_user_see_channel(test_db, user_id=guest_id, channel_id=cid)
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)", cid, guest_id,
    )
    assert await can_user_see_channel(test_db, user_id=guest_id, channel_id=cid)


@pytest.mark.asyncio
async def test_admin_sees_all(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'private', $3)",
        cid, wid, f"p-{suffix}",
    )
    assert await can_user_see_channel(test_db, user_id=owner_id, channel_id=cid)


@pytest.mark.asyncio
async def test_post_blocked_by_admins_only_policy(test_db, seed_workspace):
    wid, _ = seed_workspace
    suffix = uuid4().hex[:8]
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name, posting_policy) "
        "VALUES ($1, $2, 'public', $3, 'admins')",
        cid, wid, f"a-{suffix}",
    )
    member_id = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'M', 'member')",
        member_id, wid, f"m-{suffix}@x.com",
    )
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)", cid, member_id,
    )
    assert await can_user_see_channel(test_db, user_id=member_id, channel_id=cid)
    assert not await can_user_post_message(test_db, user_id=member_id, channel_id=cid)
    await test_db.execute(
        "UPDATE channel_members SET role = 'admin' WHERE channel_id = $1 AND user_id = $2",
        cid, member_id,
    )
    assert await can_user_post_message(test_db, user_id=member_id, channel_id=cid)
