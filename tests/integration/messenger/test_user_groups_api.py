import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_create_group(messenger_app_client, owner_token, owner_workspace_id):
    suffix = uuid4().hex[:8]
    handle = f"eng-{suffix}"
    name = f"Engineering {suffix}"
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups",
        json={"handle": handle, "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["handle"] == handle
    assert body["name"] == name


@pytest.mark.asyncio
async def test_list_groups(messenger_app_client, owner_token, owner_workspace_id):
    suffix = uuid4().hex[:8]
    handle = f"ops-{suffix}"
    name = f"Operations {suffix}"
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups",
        json={"handle": handle, "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "groups" in body
    assert any(g["handle"] == handle for g in body["groups"])


@pytest.mark.asyncio
async def test_member_cannot_create(messenger_app_client, member_token, owner_workspace_id):
    suffix = uuid4().hex[:8]
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups",
        json={"handle": f"dev-{suffix}", "name": f"Dev {suffix}"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_set_members_replaces(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace, test_db,
):
    wid, owner_id = seed_workspace

    # Create two extra users to add as members
    u1 = uuid4()
    u2 = uuid4()
    u3 = uuid4()
    s1 = uuid4().hex[:8]
    s2 = uuid4().hex[:8]
    s3 = uuid4().hex[:8]
    for uid, suffix in [(u1, s1), (u2, s2), (u3, s3)]:
        await test_db.execute(
            "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
            "VALUES ($1, $2, $3, 'human', 'U', 'member')",
            uid, wid, f"user-{suffix}@x.com",
        )

    # Create a group
    suffix = uuid4().hex[:8]
    create_r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups",
        json={"handle": f"team-{suffix}", "name": f"Team {suffix}"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert create_r.status_code == 201, create_r.text
    gid = create_r.json()["id"]

    # PUT members [u1, u2]
    r = await messenger_app_client.put(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups/{gid}/members",
        json={"user_ids": [str(u1), str(u2)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204, r.text

    # GET members returns [u1, u2]
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups/{gid}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    returned = set(r.json()["user_ids"])
    assert returned == {str(u1), str(u2)}

    # PUT members [u3] — full replace
    r = await messenger_app_client.put(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups/{gid}/members",
        json={"user_ids": [str(u3)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204, r.text

    # GET members returns only [u3]
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/user-groups/{gid}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    returned = set(r.json()["user_ids"])
    assert returned == {str(u3)}
