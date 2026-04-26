# src/breadmind/messenger/api/v1/threads.py
from __future__ import annotations
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from breadmind.messenger.api.v1.deps import get_db, get_workspace_context, WorkspaceContext
from breadmind.messenger.api.v1.messages import MessageResp, _to_resp
from breadmind.messenger.errors import NotFound
from breadmind.messenger.acl.message import can_user_see_message
from breadmind.messenger.service.message_service import get_message, list_thread_replies

router = APIRouter(tags=["threads"])


class ThreadRepliesResp:
    pass


@router.get("/workspaces/{wid}/channels/{cid}/messages/{mid}/replies")
async def get_thread_replies(
    cid: UUID,
    mid: UUID,
    limit: int = Query(50, ge=1, le=200),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_message(db, user_id=ctx.user.id, message_id=mid):
        raise NotFound("message", str(mid))

    parent = await get_message(db, channel_id=cid, message_id=mid)
    if parent.deleted_at is not None:
        raise NotFound("message", str(mid))

    replies, has_more = await list_thread_replies(
        db, channel_id=cid, parent_id=mid, limit=limit,
    )
    return {
        "parent": _to_resp(parent).model_dump(),
        "replies": [_to_resp(r).model_dump() for r in replies],
        "pagination": {"has_more": has_more, "limit": limit},
    }
