"""Per-user visible_channels cache (5min TTL, Redis)."""
from __future__ import annotations
import json
from typing import Iterable
from uuid import UUID


class VisibleChannelsCache:
    def __init__(self, redis, *, ttl_sec: int):
        self._r = redis
        self._ttl = ttl_sec

    @staticmethod
    def _key(user_id: UUID) -> str:
        return f"acl:vc:{user_id}"

    @staticmethod
    def _wkey(workspace_id: UUID) -> str:
        return f"acl:vc:ws:{workspace_id}"

    async def set(self, *, user_id: UUID,
                  channel_ids: Iterable[UUID],
                  workspace_id: UUID | None = None) -> None:
        cids = [str(cid) for cid in channel_ids]
        await self._r.set(self._key(user_id), json.dumps(cids), ex=self._ttl)
        if workspace_id is not None:
            await self._r.sadd(self._wkey(workspace_id), str(user_id))
            await self._r.expire(self._wkey(workspace_id), self._ttl)

    async def get(self, *, user_id: UUID) -> list[UUID] | None:
        v = await self._r.get(self._key(user_id))
        if v is None:
            return None
        return [UUID(s) for s in json.loads(v)]

    async def invalidate_user(self, user_id: UUID) -> None:
        await self._r.delete(self._key(user_id))

    async def invalidate_workspace(self, workspace_id: UUID) -> None:
        members = await self._r.smembers(self._wkey(workspace_id))
        if members:
            keys = [
                self._key(UUID(m.decode() if isinstance(m, bytes) else m))
                for m in members
            ]
            await self._r.delete(*keys)
        await self._r.delete(self._wkey(workspace_id))
