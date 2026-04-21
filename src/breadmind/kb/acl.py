"""ACL resolution for org KB queries.

- ``user_projects(user_id)`` — all projects the user is a member of.
- ``filter_knowledge(user_id, ids)`` — apply the hybrid project +
  channel rule from spec §7.3.
- ``can_read_channel(user_id, channel_id)`` — Slack membership check
  with 10-minute Redis cache and fail-closed on error.

A reasonable Redis client may be injected after construction via
``resolver._redis = client``. If not set, channel-membership calls
query Slack on every invocation (tests cover both paths).
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

CHANNEL_MEMBERS_TTL_SECONDS = 10 * 60


class ACLResolver:
    def __init__(self, db, slack_client):
        self._db = db
        self._slack = slack_client
        self._redis = None

    async def user_projects(self, user_id: str) -> list[UUID]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT project_id FROM org_project_members "
                "WHERE user_id = $1",
                user_id,
            )
        return [r["project_id"] for r in rows]

    async def can_read_channel(
        self, user_id: str, channel_id: str
    ) -> bool:
        members = await self._channel_members(channel_id)
        if members is None:
            return False
        return user_id in members

    async def filter_knowledge(
        self, user_id: str, knowledge_ids: list[int]
    ) -> set[int]:
        if not knowledge_ids:
            return set()
        projects = await self.user_projects(user_id)
        if not projects:
            return set()
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, source_channel
                FROM org_knowledge
                WHERE id = ANY($1::bigint[])
                  AND project_id = ANY($2::uuid[])
                """,
                knowledge_ids,
                projects,
            )
        visible: set[int] = set()
        for r in rows:
            ch = r["source_channel"]
            if ch is None:
                visible.add(r["id"])
                continue
            if await self.can_read_channel(user_id, ch):
                visible.add(r["id"])
        return visible

    async def _channel_members(
        self, channel_id: str
    ) -> set[str] | None:
        cache_key = f"acl:channel:{channel_id}"
        if self._redis is not None:
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:
                logger.warning("acl cache read failed: %s", exc)
                cached = None
            if cached is not None:
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                return set(json.loads(cached))
        try:
            resp = await self._slack.conversations_members(
                channel=channel_id, limit=1000
            )
        except Exception as exc:
            logger.warning(
                "slack conversations_members failed for %s: %s",
                channel_id, exc,
            )
            return None
        members = set(resp.get("members", []))
        if self._redis is not None:
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps(sorted(members)),
                    ex=CHANNEL_MEMBERS_TTL_SECONDS,
                )
            except Exception as exc:
                logger.warning("acl cache write failed: %s", exc)
        return members
