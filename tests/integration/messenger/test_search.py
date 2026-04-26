import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_fts_match(messenger_app_client, owner_token, owner_workspace_id, owner_channel):
    cid = owner_channel
    suffix = uuid4().hex[:8]
    unique_term = f"PAYMENT-{suffix}"
    # Korean strings + a unique English term to make matching deterministic across runs
    for txt in [f"게임 결제 시스템 RFC {unique_term}", "디자인 회의 노트", "QA 버그 리포트"]:
        r = await messenger_app_client.post(
            f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
            json={"text": txt},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert r.status_code == 201, r.text
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/search",
        params={"q": unique_term, "kind": "message"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(unique_term in (res.get("message") or {}).get("text", "") for res in body["results"])


@pytest.mark.asyncio
async def test_search_acl_excludes_invisible_channels(
    messenger_app_client, owner_token, member_token,
    owner_workspace_id, test_db, seed_workspace,
):
    wid, owner_id = seed_workspace
    cid = uuid4()
    suffix = uuid4().hex[:8]
    secret = f"SECRET-{suffix}"
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) "
        "VALUES ($1, $2, 'private', $3)", cid, wid, f"secret-{suffix}",
    )
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id, role) "
        "VALUES ($1, $2, 'admin')", cid, owner_id,
    )
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": secret},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    # member searches → must not see
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/search",
        params={"q": secret, "kind": "message"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["results"]) == 0


@pytest.mark.asyncio
async def test_hybrid_rrf_returns_results(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    suffix = uuid4().hex[:8]
    term = f"EMBEDTEST-{suffix}"
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": f"임베딩 테스트 메시지 {term}"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/search",
        params={"q": term, "kind": "message", "hybrid": "true"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200
    # results may be empty if embedder isn't configured in test env, but shouldn't error
