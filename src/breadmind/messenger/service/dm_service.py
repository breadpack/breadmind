# src/breadmind/messenger/service/dm_service.py
from __future__ import annotations
import hashlib
from uuid import UUID, uuid4

from breadmind.messenger.errors import ValidationFailed
from breadmind.messenger.service.channel_service import ChannelRow, _COLS as CHANNEL_COLS


def dm_member_hash(workspace_id: UUID, user_ids: list[UUID]) -> bytes:
    """Sorted member ids → sha256 hash."""
    sorted_ids = sorted(str(uid) for uid in set(user_ids))
    h = hashlib.sha256()
    h.update(str(workspace_id).encode())
    h.update(b"\0")
    for uid in sorted_ids:
        h.update(uid.encode())
        h.update(b"\0")
    return h.digest()


async def open_dm_or_mpdm(
    db, *, workspace_id: UUID, opener_id: UUID, member_ids: list[UUID],
) -> tuple[ChannelRow, bool]:
    """Returns (channel, created). Opener is included in member_ids if not already."""
    all_members = sorted(set(member_ids) | {opener_id})
    if len(all_members) < 2:
        raise ValidationFailed([{
            "field": "user_ids",
            "msg": "DM needs at least 2 participants (incl. opener)",
        }])
    if len(all_members) > 9:
        raise ValidationFailed([{
            "field": "user_ids",
            "msg": "MPDM max 9 participants",
        }])
    members_hash = dm_member_hash(workspace_id, all_members)

    # Look up existing
    row = await db.fetchrow(
        "SELECT channel_id FROM dm_keys WHERE workspace_id = $1 AND members_hash = $2",
        workspace_id, members_hash,
    )
    if row:
        chan_row = await db.fetchrow(
            f"SELECT {CHANNEL_COLS} FROM channels WHERE id = $1", row["channel_id"],
        )
        return ChannelRow(**dict(chan_row)), False

    # Create new
    cid = uuid4()
    kind = "dm" if len(all_members) == 2 else "mpdm"
    async with db.transaction():
        chan_row = await db.fetchrow(
            f"""INSERT INTO channels (id, workspace_id, kind, name, created_by)
                VALUES ($1, $2, $3, NULL, $4)
                RETURNING {CHANNEL_COLS}""",
            cid, workspace_id, kind, opener_id,
        )
        await db.execute(
            "INSERT INTO dm_keys (workspace_id, members_hash, channel_id) "
            "VALUES ($1, $2, $3)",
            workspace_id, members_hash, cid,
        )
        for uid in all_members:
            await db.execute(
                "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)",
                cid, uid,
            )
    return ChannelRow(**dict(chan_row)), True


async def list_dms_for_user(
    db, *, workspace_id: UUID, user_id: UUID,
) -> list[ChannelRow]:
    rows = await db.fetch(
        f"SELECT c.{', c.'.join(CHANNEL_COLS.split(', '))} "
        f"FROM channels c "
        f"JOIN channel_members cm ON cm.channel_id = c.id "
        f"WHERE c.workspace_id = $1 AND cm.user_id = $2 "
        f"AND c.kind IN ('dm', 'mpdm') "
        f"ORDER BY c.last_message_at DESC NULLS LAST, c.created_at DESC",
        workspace_id, user_id,
    )
    return [ChannelRow(**dict(r)) for r in rows]
