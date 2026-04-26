"""Default agent bootstrap on workspace creation."""
import json
from uuid import uuid4


from breadmind.messenger.service.workspace_service import create_workspace


async def test_workspace_bootstraps_default_agent(test_db):
    suffix = uuid4().hex[:8]
    row = await create_workspace(
        test_db,
        name="Bootstrapped",
        slug=f"bootstrapped-{suffix}",
        created_by=None,
    )
    agents = await test_db.fetch(
        "SELECT id, display_name, agent_config FROM workspace_users "
        "WHERE workspace_id = $1 AND kind = 'agent'",
        row.id,
    )
    assert len(agents) == 1
    assert agents[0]["display_name"] == "BreadMind"
    cfg = agents[0]["agent_config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    assert cfg["agent_class"] == "default"
    assert "kb.query" in cfg["tools_enabled"]


async def test_create_workspace_via_api_also_bootstraps(
    messenger_app_client, owner_token, test_db,
):
    """Verify create_workspace through the REST endpoint also bootstraps the agent."""
    suffix = uuid4().hex[:8]
    r = await messenger_app_client.post(
        "/api/v1/workspaces",
        json={"name": "API-Created", "slug": f"api-{suffix}"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    agents = await test_db.fetch(
        "SELECT display_name FROM workspace_users WHERE workspace_id = $1 AND kind = 'agent'",
        wid,
    )
    assert len(agents) == 1
    assert agents[0]["display_name"] == "BreadMind"
