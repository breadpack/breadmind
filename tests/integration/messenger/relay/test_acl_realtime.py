# tests/integration/messenger/relay/test_acl_realtime.py
"""ACL realtime invalidation e2e: revoke-drop / grant-emit / deactivate-revoke-all.

Covers Tasks 8 + 9 (C-bundle) end-to-end via the docker-compose test stack:
    Core publishes `acl:invalidate:user:*` events; rt-relay PSUBSCRIBE consumes
    them and emits `channel_access_revoked` / `channel_access_granted`
    envelopes to affected client connections.

All tests carry `@pytest.mark.relay_integration` and are deselected by default
(`pyproject.toml` sets `addopts = "-m 'not e2e and not relay_integration'"`).
CI's relay-integration job spins up the compose stack and runs them.

These tests intentionally reuse only the existing fixtures from `conftest.py`
(`compose_stack`, `workspace_owner`, `two_users_one_channel`) plus a small
inline 2-channel setup for the deactivate scenario, so the surface stays
minimal.
"""
from __future__ import annotations
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import websockets

from .conftest import _seed_user

pytestmark = pytest.mark.relay_integration


# --------------------------------------------------------------------------
# Local fixture: two channels + member user (for deactivate scenario).
# Built inline rather than extending conftest, per Task 10 directive
# ("do NOT add new fixtures unless absolutely necessary").
# --------------------------------------------------------------------------
@pytest_asyncio.fixture
async def two_channels_one_member(compose_stack, workspace_owner):
    """Owner + 1 member added to TWO public channels in the same workspace."""
    api, _ = compose_stack
    member = await _seed_user(
        workspace_owner.workspace_id, f"m-{uuid4().hex[:8]}@test.local"
    )
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {workspace_owner.token}"},
    ) as hc:
        ch1_resp = await hc.post(
            f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels",
            json={"kind": "public", "name": f"two-a-{uuid4().hex[:8]}"},
        )
        ch1 = ch1_resp.json()
        ch2_resp = await hc.post(
            f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels",
            json={"kind": "public", "name": f"two-b-{uuid4().hex[:8]}"},
        )
        ch2 = ch2_resp.json()
        for ch in (ch1, ch2):
            await hc.post(
                f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels/{ch['id']}/members",
                json={"user_ids": [str(member.id)]},
            )
    return workspace_owner, member, ch1["id"], ch2["id"]


# --------------------------------------------------------------------------
# Test 1: revoke drops subscription within 1s
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_revoke_drops_subscription_within_1s(compose_stack, two_users_one_channel):
    """User subscribed to a channel; admin removes them; relay must emit
    `channel_access_revoked` and stop forwarding messages from that channel."""
    api, ws_base = compose_stack
    user_a, user_b, channel_id = two_users_one_channel  # user_b is the member

    async with websockets.connect(f"{ws_base}/ws?token={user_b.token}") as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channel_ids": [channel_id]},
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert ack["type"] == "subscribed"

        # Admin (user_a / workspace_owner) removes user_b.
        async with httpx.AsyncClient(
            base_url=api,
            headers={"Authorization": f"Bearer {user_a.token}"},
        ) as hc:
            r = await hc.delete(
                f"/api/v1/workspaces/{user_a.workspace_id}"
                f"/channels/{channel_id}/members/{user_b.id}"
            )
            assert r.status_code in (200, 204)

        revoked = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert revoked["type"] == "channel_access_revoked"
        assert revoked["payload"]["channel_id"] == str(channel_id)

        # Posting a message in the channel must NOT reach this WS.
        async with httpx.AsyncClient(
            base_url=api,
            headers={"Authorization": f"Bearer {user_a.token}"},
        ) as hc:
            await hc.post(
                f"/api/v1/workspaces/{user_a.workspace_id}"
                f"/channels/{channel_id}/messages",
                json={"text": "should not reach removed user"},
            )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.recv(), 1.0)


# --------------------------------------------------------------------------
# Test 2: grant emits Granted; subsequent Subscribe succeeds
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_grant_emits_granted_event(compose_stack, workspace_owner):
    """Connected user (no membership yet) → admin adds them to a private
    channel → relay must emit `channel_access_granted`; the subsequent
    Subscribe call must then succeed (cache reflects new membership)."""
    api, ws_base = compose_stack
    admin = workspace_owner

    # Seed a non-member user in the same workspace.
    user = await _seed_user(
        admin.workspace_id, f"new-{uuid4().hex[:8]}@test.local"
    )

    # Create a private channel (user is NOT a member yet).
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {admin.token}"},
    ) as hc:
        ch_resp = await hc.post(
            f"/api/v1/workspaces/{admin.workspace_id}/channels",
            json={"kind": "private", "name": f"priv-{uuid4().hex[:8]}"},
        )
        assert ch_resp.status_code in (200, 201)
        channel_id = ch_resp.json()["id"]

    async with websockets.connect(f"{ws_base}/ws?token={user.token}") as ws:
        # Admin adds the user → triggers acl:invalidate:user:<uid>:channel:<cid>:add.
        async with httpx.AsyncClient(
            base_url=api,
            headers={"Authorization": f"Bearer {admin.token}"},
        ) as hc:
            r = await hc.post(
                f"/api/v1/workspaces/{admin.workspace_id}"
                f"/channels/{channel_id}/members",
                json={"user_ids": [str(user.id)]},
            )
            assert r.status_code in (200, 201)

        granted = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert granted["type"] == "channel_access_granted"
        assert granted["payload"]["channel_id"] == str(channel_id)

        # Subscribe should now succeed (cache invalidated and refreshed).
        await ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channel_ids": [channel_id]},
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert ack["type"] == "subscribed"


# --------------------------------------------------------------------------
# Test 3: deactivate user revokes ALL subscribed channels
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_user_deactivate_revokes_all_channels(
    compose_stack, two_channels_one_member,
):
    """User subscribed to 2 channels; admin deactivates user; relay must
    emit `channel_access_revoked` for both channel_ids."""
    api, ws_base = compose_stack
    admin, member, ch1_id, ch2_id = two_channels_one_member

    async with websockets.connect(f"{ws_base}/ws?token={member.token}") as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channel_ids": [ch1_id, ch2_id]},
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert ack["type"] == "subscribed"

        # Admin deactivates the user → publishes `acl:invalidate:user:<uid>`,
        # relay translates to per-channel revokes for each subscribed channel.
        async with httpx.AsyncClient(
            base_url=api,
            headers={"Authorization": f"Bearer {admin.token}"},
        ) as hc:
            r = await hc.delete(
                f"/api/v1/workspaces/{admin.workspace_id}/users/{member.id}"
            )
            assert r.status_code in (200, 204)

        seen: set[str] = set()
        for _ in range(2):
            ev = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
            assert ev["type"] == "channel_access_revoked"
            seen.add(ev["payload"]["channel_id"])
        assert seen == {str(ch1_id), str(ch2_id)}
