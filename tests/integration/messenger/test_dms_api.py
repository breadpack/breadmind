import pytest
from uuid import uuid4


async def _create_member(test_db, workspace_id, suffix=None):
    """Helper: insert a workspace_user and return their id."""
    uid = uuid4()
    sfx = suffix or uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'TestUser', 'member')",
        uid, workspace_id, f"dm-user-{sfx}@test.com",
    )
    return uid


@pytest.mark.asyncio
async def test_open_new_dm_201(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace, test_db,
):
    wid, owner_id = seed_workspace
    headers = {"Authorization": f"Bearer {owner_token}"}
    other_id = await _create_member(test_db, wid)

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "dm"


@pytest.mark.asyncio
async def test_reopen_same_dm_200(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace, test_db,
):
    wid, owner_id = seed_workspace
    headers = {"Authorization": f"Bearer {owner_token}"}
    other_id = await _create_member(test_db, wid, suffix=uuid4().hex[:8])

    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers=headers,
    )
    assert r1.status_code == 201, r1.text
    cid1 = r1.json()["id"]

    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(other_id)]},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == cid1


@pytest.mark.asyncio
async def test_mpdm_3_people_201(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace, test_db,
):
    wid, owner_id = seed_workspace
    headers = {"Authorization": f"Bearer {owner_token}"}
    uid2 = await _create_member(test_db, wid, suffix=uuid4().hex[:8])
    uid3 = await _create_member(test_db, wid, suffix=uuid4().hex[:8])

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": [str(uid2), str(uid3)]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "mpdm"


@pytest.mark.asyncio
async def test_mpdm_9_person_cap_422(
    messenger_app_client, owner_token, owner_workspace_id, seed_workspace, test_db,
):
    wid, owner_id = seed_workspace
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Create 9 extra members (owner + 9 = 10 total → exceeds cap of 9)
    extra_ids = []
    for _ in range(9):
        uid = await _create_member(test_db, wid, suffix=uuid4().hex[:8])
        extra_ids.append(str(uid))

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/dms",
        json={"user_ids": extra_ids},
        headers=headers,
    )
    assert r.status_code == 422, r.text
