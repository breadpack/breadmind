from __future__ import annotations
from uuid import UUID

from .channel import can_user_see_channel, _get_user_role


async def can_user_see_message(db, *, user_id: UUID, message_id: UUID) -> bool:
    row = await db.fetchrow(
        "SELECT channel_id, deleted_at FROM messages WHERE id = $1", message_id,
    )
    if row is None:
        return False
    return await can_user_see_channel(db, user_id=user_id, channel_id=row["channel_id"])


async def can_user_edit_message(db, *, user_id: UUID, message_id: UUID) -> bool:
    msg = await db.fetchrow(
        "SELECT author_id, channel_id, deleted_at FROM messages WHERE id = $1", message_id,
    )
    if msg is None or msg["deleted_at"] is not None:
        return False
    user = await _get_user_role(db, user_id)
    if user is None:
        return False
    role, _ = user
    if role in ("owner", "admin"):
        return True
    if msg["author_id"] != user_id:
        return False
    return await can_user_see_channel(db, user_id=user_id, channel_id=msg["channel_id"])


async def can_user_delete_message(db, *, user_id: UUID, message_id: UUID) -> bool:
    """Same as edit for V1 (author or admin)."""
    return await can_user_edit_message(db, user_id=user_id, message_id=message_id)
