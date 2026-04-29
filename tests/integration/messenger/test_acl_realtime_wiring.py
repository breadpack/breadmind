"""End-to-end wiring tests for ACL realtime publish at the 7 mutation sites.

Each test asserts that the right `acl:invalidate:...` channel is published
when the corresponding mutation route is invoked. Uses `fakeredis` via the
shared `redis_client` fixture (also wired into `messenger_app.state.redis`).
"""
from __future__ import annotations

from uuid import uuid4

import pytest_asyncio


@pytest_asyncio.fixture
async def pubsub_listener(redis_client):
    """Subscribe to all `acl:invalidate:*` channels and capture messages."""
    ps = redis_client.pubsub()
    await ps.psubscribe("acl:invalidate:*")
    # Drain the subscribe ack.
    await ps.get_message(timeout=0.1)
    try:
        yield ps
    finally:
        await ps.aclose()


async def _drain_acl_messages(ps, *, timeout: float = 0.5) -> list[str]:
    """Read all pmessages until timeout. Return decoded channel names."""
    out: list[str] = []
    while True:
        msg = await ps.get_message(timeout=timeout)
        if msg is None:
            break
        if msg.get("type") != "pmessage":
            continue
        ch = msg["channel"]
        if isinstance(ch, bytes):
            ch = ch.decode()
        out.append(ch)
    return out


async def test_add_member_endpoint_publishes_add(
    messenger_app_client, owner_token, owner_workspace_id, test_db, pubsub_listener,
):
    """POST /channels/{cid}/members publishes acl:invalidate:user:<uid>:channel:<cid>:add."""
    name = f"join-{uuid4().hex[:8]}"
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]

    new_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'J', 'member')",
        new_uid, owner_workspace_id, f"joiner-{suffix}@x.com",
    )

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members",
        json={"user_ids": [str(new_uid)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text

    chans = await _drain_acl_messages(pubsub_listener)
    expected = f"acl:invalidate:user:{new_uid}:channel:{cid}:add"
    assert expected in chans, f"expected {expected} in {chans}"


async def test_remove_member_endpoint_publishes_remove(
    messenger_app_client, owner_token, owner_workspace_id, test_db, pubsub_listener,
):
    """DELETE /channels/{cid}/members/{uid} publishes :remove."""
    name = f"leave-{uuid4().hex[:8]}"
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    cid = create.json()["id"]

    new_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'J', 'member')",
        new_uid, owner_workspace_id, f"leaver-{suffix}@x.com",
    )
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members",
        json={"user_ids": [str(new_uid)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    # Drain the add publish.
    await _drain_acl_messages(pubsub_listener)

    r = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members/{new_uid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204

    chans = await _drain_acl_messages(pubsub_listener)
    expected = f"acl:invalidate:user:{new_uid}:channel:{cid}:remove"
    assert expected in chans, f"expected {expected} in {chans}"


async def test_open_dm_publishes_add_for_each_participant(
    messenger_app_client, owner_token, seed_workspace, test_db, pubsub_listener,
):
    """POST /dms publishes :add for both participants when DM is created."""
    wid, owner_id = seed_workspace
    other_id = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'O', 'member')",
        other_id, wid, f"dm-other-{suffix}@x.com",
    )

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    chans = await _drain_acl_messages(pubsub_listener)
    assert f"acl:invalidate:user:{owner_id}:channel:{cid}:add" in chans
    assert f"acl:invalidate:user:{other_id}:channel:{cid}:add" in chans


async def test_open_existing_dm_does_not_publish(
    messenger_app_client, owner_token, seed_workspace, test_db, pubsub_listener,
):
    """Reopening an existing DM (created=False) must not publish."""
    wid, owner_id = seed_workspace
    other_id = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'O', 'member')",
        other_id, wid, f"dm-existing-{suffix}@x.com",
    )
    # First call creates.
    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r1.status_code == 201
    await _drain_acl_messages(pubsub_listener)  # drain creation publishes.

    # Second call returns existing → no publish.
    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r2.status_code == 200
    chans = await _drain_acl_messages(pubsub_listener)
    assert chans == []


async def test_archive_channel_does_not_publish(
    messenger_app_client, owner_token, owner_workspace_id, test_db, pubsub_listener,
):
    """Spec D8: archive != revoke. Members keep visibility, no :remove published."""
    name = f"arch-{uuid4().hex[:8]}"
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    cid = create.json()["id"]

    new_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'M', 'member')",
        new_uid, owner_workspace_id, f"arch-m-{suffix}@x.com",
    )
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members",
        json={"user_ids": [str(new_uid)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await _drain_acl_messages(pubsub_listener)  # drain add publishes.

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/archive",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204

    chans = await _drain_acl_messages(pubsub_listener)
    # Spec D8: archive must not publish anything for this channel.
    offending = [ch for ch in chans if f":channel:{cid}:" in ch]
    assert offending == [], f"archive must not publish, got {offending}"


async def test_deactivate_user_publishes_user_invalidate(
    messenger_app_client, owner_token, owner_workspace_id, test_db, pubsub_listener,
):
    """DELETE /users/{uid} publishes acl:invalidate:user:<uid>."""
    target_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'D', 'member')",
        target_uid, owner_workspace_id, f"deact-{suffix}@x.com",
    )

    r = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/users/{target_uid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204

    chans = await _drain_acl_messages(pubsub_listener)
    expected = f"acl:invalidate:user:{target_uid}"
    assert expected in chans, f"expected {expected} in {chans}"


async def test_update_user_role_service_publishes_when_redis_provided(
    test_db, seed_workspace, redis_client,
):
    """update_user_role(redis=...) publishes acl:invalidate:user:<uid>.

    No route exists for role change; verifies the service-level wiring directly.
    """
    from breadmind.messenger.service.user_service import update_user_role

    wid, _ = seed_workspace
    target_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'R', 'member')",
        target_uid, wid, f"role-{suffix}@x.com",
    )

    ps = redis_client.pubsub()
    await ps.psubscribe("acl:invalidate:*")
    await ps.get_message(timeout=0.1)
    try:
        await update_user_role(
            test_db, workspace_id=wid, user_id=target_uid, role="admin",
            redis=redis_client,
        )
        chans = await _drain_acl_messages(ps)
        assert f"acl:invalidate:user:{target_uid}" in chans, chans
    finally:
        await ps.aclose()


async def test_update_user_role_service_no_publish_when_redis_none(
    test_db, seed_workspace, redis_client,
):
    """update_user_role without redis does not publish (backward-compat default)."""
    from breadmind.messenger.service.user_service import update_user_role

    wid, _ = seed_workspace
    target_uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'R2', 'member')",
        target_uid, wid, f"role2-{suffix}@x.com",
    )

    ps = redis_client.pubsub()
    await ps.psubscribe("acl:invalidate:*")
    await ps.get_message(timeout=0.1)
    try:
        await update_user_role(
            test_db, workspace_id=wid, user_id=target_uid, role="admin",
        )
        chans = await _drain_acl_messages(ps)
        assert chans == [], f"expected no publish, got {chans}"
    finally:
        await ps.aclose()
