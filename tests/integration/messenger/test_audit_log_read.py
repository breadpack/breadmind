import pytest


@pytest.mark.asyncio
async def test_audit_read_admin_only(messenger_app_client, member_token, owner_workspace_id):
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/audit-log",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_audit_read_admin_returns_entries(
    test_db, messenger_app_client, owner_token, owner_workspace_id,
):
    await test_db.execute(
        "INSERT INTO audit_log (action, result, workspace_id, entity_kind, entity_id, payload, occurred_at) "
        "VALUES ('create', '', $1, 'channel', gen_random_uuid(), '{}'::jsonb, now())",
        owner_workspace_id,
    )
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/audit-log",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "entries" in body
    assert len(body["entries"]) >= 1


@pytest.mark.asyncio
async def test_create_channel_writes_audit(
    test_db, messenger_app_client, owner_token, owner_workspace_id,
):
    import json
    from uuid import uuid4
    name = f"audit-test-{uuid4().hex[:8]}"
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels",
        json={"kind": "public", "name": name},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    rows = await test_db.fetch(
        "SELECT entity_kind, action, payload FROM audit_log "
        "WHERE workspace_id = $1 AND entity_kind = 'channel' AND action = 'create' "
        "ORDER BY occurred_at DESC LIMIT 5",
        owner_workspace_id,
    )
    assert any(
        (r["payload"]["name"] if isinstance(r["payload"], dict) else json.loads(r["payload"])["name"]) == name
        for r in rows
    )
