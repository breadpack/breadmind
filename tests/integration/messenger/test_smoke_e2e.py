"""Smoke E2E — full user journey: workspace → channel → message → invite → search."""
from uuid import uuid4

import pytest

from breadmind.messenger.auth.invite import create_invite, accept_invite
from breadmind.messenger.auth.session import create_session
from breadmind.messenger.service.workspace_service import create_workspace


KEY = "00" * 32


@pytest.mark.asyncio
async def test_full_user_journey(messenger_app_client, test_db):
    """End-to-end:
    1) Create workspace + auto-bootstraps agent (Task 37)
    2) Insert owner user, create session (Tasks 15, 17)
    3) Owner creates a public channel (Task 26)
    4) Owner posts a message (Task 27)
    5) Owner invites Alice; Alice accepts (Task 18)
    6) Alice creates session, joins channel, posts a message
    7) Owner searches for unique term in Alice's text → finds it (Task 36)
    """
    suffix = uuid4().hex[:8]

    # 1) Create workspace (auto-bootstraps default agent)
    workspace = await create_workspace(
        test_db,
        name="Smoke Workspace",
        slug=f"smoke-{suffix}",
        created_by=None,
    )
    wid = workspace.id

    # Verify the bootstrap created the agent
    agent_count = await test_db.fetchval(
        "SELECT count(*) FROM workspace_users WHERE workspace_id = $1 AND kind = 'agent'",
        wid,
    )
    assert agent_count == 1

    # 2) Insert owner + session
    owner_uid = uuid4()
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'Owner', 'owner')",
        owner_uid, wid, f"owner-{suffix}@smoke.com",
    )
    sess = await create_session(
        test_db, KEY, user_id=owner_uid, workspace_id=wid,
        access_ttl_min=30, refresh_ttl_days=30,
    )
    headers = {"Authorization": f"Bearer {sess.access_token}"}

    # 3) Owner creates channel
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels",
        json={"kind": "public", "name": f"general-{suffix}"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    # 4) Owner posts a message
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": "회사 OKR Q3"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # 5) Invite Alice + accept
    invite = await create_invite(
        test_db, workspace_id=wid, email=f"alice-{suffix}@smoke.com",
        invited_by=owner_uid, role="member", ttl_days=14,
    )
    alice_uid = await accept_invite(
        test_db, token=invite.token, display_name="Alice",
    )
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)",
        cid, alice_uid,
    )

    # 6) Alice session + post
    alice_sess = await create_session(
        test_db, KEY, user_id=alice_uid, workspace_id=wid,
        access_ttl_min=30, refresh_ttl_days=30,
    )
    a_headers = {"Authorization": f"Bearer {alice_sess.access_token}"}
    unique_term = f"PAYMENT-RFC-{suffix}"
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": f"결제 시스템 RFC {unique_term} 검토 부탁드립니다"},
        headers=a_headers,
    )
    assert r.status_code == 201, r.text

    # 7) Owner searches for unique term → must find Alice's message
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/search",
        params={"q": unique_term, "kind": "message"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert any(
        unique_term in (res.get("message") or {}).get("text", "")
        for res in results
    ), f"smoke: unique term {unique_term} not found in {results}"
