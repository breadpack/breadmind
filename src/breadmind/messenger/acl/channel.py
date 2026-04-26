"""Channel visibility + posting ACL."""
from __future__ import annotations
from uuid import UUID


async def _get_user_role(db, user_id: UUID) -> tuple[str, UUID] | None:
    row = await db.fetchrow(
        "SELECT role, workspace_id FROM workspace_users "
        "WHERE id = $1 AND deactivated_at IS NULL",
        user_id,
    )
    if row is None:
        return None
    return row["role"], row["workspace_id"]


async def _get_channel(db, channel_id: UUID):
    return await db.fetchrow(
        "SELECT id, workspace_id, kind, posting_policy, is_archived "
        "FROM channels WHERE id = $1", channel_id,
    )


async def _user_is_channel_member(db, user_id: UUID, channel_id: UUID,
                                   *, require_admin: bool = False) -> bool:
    role_filter = " AND role = 'admin'" if require_admin else ""
    row = await db.fetchrow(
        f"SELECT 1 FROM channel_members WHERE channel_id = $1 AND user_id = $2{role_filter}",
        channel_id, user_id,
    )
    return row is not None


async def can_user_see_channel(db, *, user_id: UUID, channel_id: UUID) -> bool:
    user = await _get_user_role(db, user_id)
    if user is None:
        return False
    role, user_wid = user
    chan = await _get_channel(db, channel_id)
    if chan is None or chan["workspace_id"] != user_wid:
        return False
    if role in ("owner", "admin"):
        return True
    if chan["kind"] == "public" and role == "member":
        return True
    return await _user_is_channel_member(db, user_id, channel_id)


async def can_user_post_message(db, *, user_id: UUID, channel_id: UUID) -> bool:
    user = await _get_user_role(db, user_id)
    if user is None:
        return False
    role, user_wid = user
    chan = await _get_channel(db, channel_id)
    if chan is None or chan["workspace_id"] != user_wid or chan["is_archived"]:
        return False
    if role in ("owner", "admin"):
        return True
    if not await can_user_see_channel(db, user_id=user_id, channel_id=channel_id):
        return False
    if chan["posting_policy"] == "admins":
        return await _user_is_channel_member(db, user_id, channel_id, require_admin=True)
    if chan["posting_policy"] == "specific_roles":
        return await _user_is_channel_member(db, user_id, channel_id, require_admin=True)
    if role == "guest":
        return await _user_is_channel_member(db, user_id, channel_id)
    return True


async def can_user_admin_channel(db, *, user_id: UUID, channel_id: UUID) -> bool:
    user = await _get_user_role(db, user_id)
    if user is None:
        return False
    role, _ = user
    if role in ("owner", "admin"):
        return True
    return await _user_is_channel_member(db, user_id, channel_id, require_admin=True)
