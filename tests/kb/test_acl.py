"""Tests for breadmind.kb.acl."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from breadmind.kb.acl import ACLResolver
from breadmind.storage.database import Database


async def _seed_project(conn, name: str, team: str = "T1") -> uuid.UUID:
    row = await conn.fetchrow(
        "INSERT INTO org_projects(name, slack_team_id) VALUES($1,$2) "
        "RETURNING id",
        name, team,
    )
    return row["id"]


async def test_user_projects_returns_memberships(
    test_db: Database, fake_redis
) -> None:
    slack = AsyncMock()
    async with test_db.acquire() as conn:
        p1 = await _seed_project(conn, "alpha")
        p2 = await _seed_project(conn, "beta")
        p3 = await _seed_project(conn, "gamma")
        for pid in (p1, p2):
            await conn.execute(
                "INSERT INTO org_project_members(project_id, user_id, role) "
                "VALUES($1, 'U1', 'member')",
                pid,
            )
    r = ACLResolver(db=test_db, slack_client=slack)
    r._redis = fake_redis
    projects = await r.user_projects("U1")
    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM org_project_members")
        await conn.execute(
            "DELETE FROM org_projects WHERE id = ANY($1::uuid[])",
            [p1, p2, p3],
        )
    assert set(projects) == {p1, p2}


async def test_user_projects_empty_when_no_membership(
    test_db: Database,
) -> None:
    r = ACLResolver(db=test_db, slack_client=AsyncMock())
    assert await r.user_projects("never-seen") == []


async def test_can_read_channel_hits_slack_and_caches(
    test_db: Database, fake_redis
) -> None:
    slack = AsyncMock()
    slack.conversations_members.return_value = {
        "ok": True,
        "members": ["U1", "U2"],
    }
    r = ACLResolver(db=test_db, slack_client=slack)
    r._redis = fake_redis
    assert await r.can_read_channel("U1", "C123") is True
    assert await r.can_read_channel("U2", "C123") is True
    assert await r.can_read_channel("U9", "C123") is False
    assert slack.conversations_members.await_count == 1


async def test_can_read_channel_fail_closed_on_slack_error(
    test_db: Database, fake_redis
) -> None:
    slack = AsyncMock()
    slack.conversations_members.side_effect = RuntimeError("slack down")
    r = ACLResolver(db=test_db, slack_client=slack)
    r._redis = fake_redis
    assert await r.can_read_channel("U1", "C404") is False


async def test_can_read_channel_uses_cached_value(
    test_db: Database, fake_redis
) -> None:
    slack = AsyncMock()
    slack.conversations_members.return_value = {
        "ok": True,
        "members": ["U1"],
    }
    r = ACLResolver(db=test_db, slack_client=slack)
    r._redis = fake_redis
    await r.can_read_channel("U1", "C777")
    # Subsequent failure of Slack should still hit cache.
    slack.conversations_members.side_effect = RuntimeError("down")
    assert await r.can_read_channel("U1", "C777") is True
