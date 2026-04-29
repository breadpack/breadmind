"""API-level e2e: client_msg_id body dedup returns same Message row across retries."""
import json
from uuid import uuid4


async def test_post_twice_with_same_client_msg_id_returns_same_row(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    """Two POSTs with identical client_msg_id resolve to the same Message id."""
    cid = owner_channel
    cmid = str(uuid4())
    body = {"text": "hello", "client_msg_id": cmid}
    headers = {"Authorization": f"Bearer {owner_token}"}

    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json=body, headers=headers,
    )
    assert r1.status_code == 201, r1.text
    msg1 = r1.json()

    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json=body, headers=headers,
    )
    assert r2.status_code == 201, r2.text
    msg2 = r2.json()

    assert msg1["id"] == msg2["id"]


async def test_post_with_existing_client_msg_id_recovers_from_unique_violation(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
    seed_workspace, test_db, redis_client,
):
    """Race-recovery path: Redis misses, DB UNIQUE collides, handler returns the winner.

    Simulates two concurrent POSTs that both miss the Redis dedup fast path
    by inserting the "winning" row directly into DB (bypassing Redis), then
    issuing a POST with the same client_msg_id. The handler must catch
    asyncpg.UniqueViolationError, look up the existing row, and return it
    with idempotent semantics. Subsequent retries must hit the Redis fast
    path because the handler should have populated it on recovery.
    """
    _, owner_id = seed_workspace
    cid = owner_channel
    cmid = uuid4()
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Pre-insert the "winner" row directly, bypassing Redis dedup.
    # ts_seq is allocated via next_ts_seq() for normal posts; here we
    # pick ts_seq=1 manually for the seed row. The next API POST will
    # bump the channel counter past 1.
    winner_id = uuid4()
    await test_db.execute(
        """INSERT INTO messages
              (id, workspace_id, channel_id, author_id, parent_id, kind, text,
               blocks, client_msg_id, ts_seq)
           VALUES ($1, $2, $3, $4, NULL, 'text', 'pre-existing',
                   $5::jsonb, $6, 1)""",
        winner_id, owner_workspace_id, cid, owner_id,
        json.dumps([]), cmid,
    )

    # POST with the same client_msg_id. Redis misses (we never populated it),
    # post_message hits the DB UNIQUE index and raises UniqueViolationError,
    # the handler recovers by looking up the winner.
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "racer", "client_msg_id": str(cmid)}, headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == str(winner_id)

    # Redis should now contain the dedup pointer to the winner so subsequent
    # retries hit the fast path instead of repeating the DB collision.
    key = f"msg:dedup:{owner_id}:{cid}:{cmid}"
    cached = await redis_client.get(key)
    assert cached is not None
    cached_str = cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
    assert cached_str == str(winner_id)


async def test_different_client_msg_ids_create_distinct_rows(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    """Distinct client_msg_id values must produce distinct Message rows."""
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "first", "client_msg_id": str(uuid4())}, headers=headers,
    )
    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "second", "client_msg_id": str(uuid4())}, headers=headers,
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
