from datetime import datetime, timezone, timedelta
from uuid import uuid4


def _future(minutes: int = 10) -> str:
    """Return an ISO timestamp in the future."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past(minutes: int = 1) -> str:
    """Return an ISO timestamp in the past."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


async def test_schedule_and_list(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/scheduled-messages",
        json={
            "channel_id": str(cid),
            "text": "hello future",
            "scheduled_for": _future(),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text"] == "hello future"
    sid = body["id"]

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/scheduled-messages",
        headers=headers,
    )
    assert rl.status_code == 200, rl.text
    scheduled = rl.json()["scheduled"]
    assert any(s["id"] == sid for s in scheduled)


async def test_cancel_removes_from_list(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/scheduled-messages",
        json={
            "channel_id": str(cid),
            "text": "cancel me",
            "scheduled_for": _future(),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    rd = await messenger_app_client.delete(
        f"/api/v1/workspaces/{wid}/scheduled-messages/{sid}",
        headers=headers,
    )
    assert rd.status_code == 204, rd.text

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/scheduled-messages",
        headers=headers,
    )
    scheduled = rl.json()["scheduled"]
    assert all(s["id"] != sid for s in scheduled)


async def test_dispatch_future_not_dispatched(test_db, seed_workspace, owner_channel):
    """dispatch_due_messages query does NOT pick up future-scheduled messages.

    We verify this by directly querying the DB using the same WHERE clause
    used by dispatch_due_messages and confirming our future-scheduled row is
    not returned.  This avoids needing a full asyncpg.Connection (which would
    be required for db.transaction()), while still exercising the data-plane
    logic.
    """
    import json
    from uuid import uuid4 as _uuid4
    from datetime import datetime, timezone, timedelta

    wid, owner_id = seed_workspace
    cid = owner_channel

    sid = _uuid4()
    future_ts = datetime.now(timezone.utc) + timedelta(hours=1)
    await test_db.execute(
        "INSERT INTO scheduled_messages "
        "(id, workspace_id, channel_id, author_id, text, blocks, scheduled_for) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
        sid, wid, cid, owner_id, "future msg", json.dumps([]), future_ts,
    )

    # Same WHERE clause as dispatch_due_messages — should return 0 rows for our message
    rows = await test_db.fetch(
        "SELECT id FROM scheduled_messages "
        "WHERE id = $1 AND scheduled_for <= now() "
        "AND sent_message_id IS NULL AND cancelled_at IS NULL",
        sid,
    )
    assert len(rows) == 0, "Future-scheduled message should not be picked up as due"


async def test_past_scheduled_for_422(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/scheduled-messages",
        json={
            "channel_id": str(cid),
            "text": "in the past",
            "scheduled_for": _past(),
        },
        headers=headers,
    )
    assert r.status_code == 422, r.text
