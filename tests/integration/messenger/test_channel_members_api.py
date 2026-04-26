import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_channel_member_add_remove(
    messenger_app_client, owner_token, owner_workspace_id, test_db,
):
    name = f"join-{uuid4().hex[:8]}"
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
        new_uid, owner_workspace_id, f"joiner-{suffix}@x.com",
    )
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members",
        json={"user_ids": [str(new_uid)]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    rd = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/members/{new_uid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert rd.status_code == 204
