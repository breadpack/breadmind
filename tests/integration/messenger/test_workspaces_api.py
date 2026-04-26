from uuid import uuid4


async def test_create_workspace_returns_201(messenger_app_client, owner_token):
    suffix = uuid4().hex[:8]
    r = await messenger_app_client.post(
        "/api/v1/workspaces",
        json={"name": "Acme", "slug": f"acme-{suffix}"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == f"acme-{suffix}"
    assert body["plan"] == "free"


async def test_list_workspaces_only_user_workspaces(
    messenger_app_client, owner_token, owner_workspace_id,
):
    r = await messenger_app_client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    ids = [w["id"] for w in r.json()]
    assert str(owner_workspace_id) in ids


async def test_get_workspace_404_for_other(messenger_app_client, owner_token):
    other = uuid4()
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{other}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code in (403, 404)


async def test_patch_workspace_admin_only(
    messenger_app_client, member_token, owner_workspace_id,
):
    r = await messenger_app_client.patch(
        f"/api/v1/workspaces/{owner_workspace_id}",
        json={"name": "NewName"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert r.status_code == 403, r.text
