# src/breadmind/messenger/api/v1/pins.py
from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, status

from breadmind.messenger.api.v1.deps import get_db, get_workspace_context, WorkspaceContext
from breadmind.messenger.api.v1.messages import MessageResp, _to_resp
from breadmind.messenger.errors import NotFound
from breadmind.messenger.acl.channel import can_user_see_channel
from breadmind.messenger.service.pin_service import pin_message, unpin_message, list_pins

router = APIRouter(tags=["pins"])


@router.post(
    "/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def pin_message_endpoint(
    cid: UUID,
    mid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise NotFound("channel", str(cid))
    await pin_message(db, channel_id=cid, message_id=mid, pinned_by=ctx.user.id)


@router.delete(
    "/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unpin_message_endpoint(
    cid: UUID,
    mid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise NotFound("channel", str(cid))
    await unpin_message(db, channel_id=cid, message_id=mid)


@router.get("/workspaces/{wid}/channels/{cid}/pins")
async def list_pins_endpoint(
    cid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise NotFound("channel", str(cid))
    rows = await list_pins(db, channel_id=cid)
    return {"pins": [_to_resp(r).model_dump() for r in rows]}
