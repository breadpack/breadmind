"""ACL invalidation event publisher (B/A granularity).

B (per-(uid, cid, op)): channel membership changes, DM creation, channel delete.
A (per-uid):            user-wide changes (deactivate, role change).

Channel naming:
    acl:invalidate:user:<uid>:channel:<cid>:add
    acl:invalidate:user:<uid>:channel:<cid>:remove
    acl:invalidate:user:<uid>

Failure mode: log and swallow. The mutation already succeeded; missing a
publish is recoverable via VisibleChannelsCache 5min TTL refresh.

Note: Site 5 from spec D8 (delete_channel `:remove` per member) is deferred
until a hard-delete endpoint is added; archive_channel does NOT publish per
spec D8 archive policy ("archive != revoke; members keep read-only visibility").
Track as FU for the M2-deps-ACL plan.
"""
from __future__ import annotations
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def publish_user_channel_change(
    redis, *, user_id: UUID, channel_id: UUID, op: str,
) -> None:
    if op not in ("add", "remove"):
        raise ValueError(f"op must be add or remove, got {op}")
    ch = f"acl:invalidate:user:{user_id}:channel:{channel_id}:{op}"
    try:
        await redis.publish(ch, "")
    except Exception as e:  # noqa: BLE001
        logger.warning("acl invalidate publish failed ch=%s: %s", ch, e)


async def publish_user_invalidate(redis, *, user_id: UUID) -> None:
    ch = f"acl:invalidate:user:{user_id}"
    try:
        await redis.publish(ch, "")
    except Exception as e:  # noqa: BLE001
        logger.warning("acl invalidate publish failed ch=%s: %s", ch, e)
