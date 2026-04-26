from uuid import uuid4


async def test_create_public_channel(messenger_app_client, owner_token, owner_workspace_id):
    name = f"general-{uuid4().hex[:8]}"
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == name
    assert body["kind"] == "public"


async def test_list_channels(messenger_app_client, owner_token, owner_workspace_id):
    name = f"alpha-{uuid4().hex[:8]}"
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        params={"kind": "public"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "channels" in body
    assert any(c["name"] == name for c in body["channels"])


async def test_archive_unarchive(messenger_app_client, owner_token, owner_workspace_id):
    name = f"tmp-{uuid4().hex[:8]}"
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    cid = create.json()["id"]
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/archive",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204
    g = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert g.json()["is_archived"] is True
