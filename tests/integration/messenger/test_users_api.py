from uuid import uuid4


async def test_list_users(messenger_app_client, owner_token, owner_workspace_id):
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/users",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "users" in body
    assert len(body["users"]) >= 1


async def test_get_user_self(messenger_app_client, owner_token, owner_workspace_id, seed_workspace):
    _, uid = seed_workspace
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/users/{uid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(uid)


async def test_invite_user(messenger_app_client, owner_token, owner_workspace_id):
    # use unique email per run to avoid collision with workspace_invites' UNIQUE token_hash
    email = f"newbie-{uuid4().hex[:8]}@x.com"
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/users",
        json={"email": email, "role": "member"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == email


async def test_lookup_by_email(messenger_app_client, owner_token, owner_workspace_id, test_db, seed_workspace):
    # seed_workspace uses uuid-suffixed email; query for that exact email
    _, owner_id = seed_workspace
    row = await test_db.fetchrow("SELECT email FROM workspace_users WHERE id = $1", owner_id)
    seeded_email = row["email"]
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/users",
        params={"email": seeded_email},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    users = r.json()["users"]
    assert any(u["email"] == seeded_email for u in users)


async def test_patch_profile_self(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace,
):
    _, uid = seed_workspace
    r = await messenger_app_client.patch(
        f"/api/v1/workspaces/{owner_workspace_id}/users/{uid}/profile",
        json={"display_name": "Updated", "status_text": "lunch"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Updated"
    assert body["status_text"] == "lunch"
