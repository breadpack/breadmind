# src/breadmind/messenger/api/v1/reactions.py
from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import get_db, get_workspace_context, WorkspaceContext
from breadmind.messenger.errors import NotFound
from breadmind.messenger.acl.message import can_user_see_message
from breadmind.messenger.service.reaction_service import (
    add_reaction, remove_reaction, list_reactions_for_message,
)

router = APIRouter(tags=["reactions"])


class AddReactionReq(BaseModel):
    emoji: str


@router.post(
    "/workspaces/{wid}/channels/{cid}/messages/{mid}/reactions",
    status_code=status.HTTP_201_CREATED,
)
async def add_reaction_endpoint(
    cid: UUID,
    mid: UUID,
    body: AddReactionReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_message(db, user_id=ctx.user.id, message_id=mid):
        raise NotFound("message", str(mid))
    await add_reaction(db, message_id=mid, user_id=ctx.user.id, emoji=body.emoji)
    return {"message_id": str(mid), "emoji": body.emoji}


@router.delete(
    "/workspaces/{wid}/channels/{cid}/messages/{mid}/reactions/{emoji:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_reaction_endpoint(
    cid: UUID,
    mid: UUID,
    emoji: str = Path(...),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_message(db, user_id=ctx.user.id, message_id=mid):
        raise NotFound("message", str(mid))
    await remove_reaction(db, message_id=mid, user_id=ctx.user.id, emoji=emoji)


@router.get("/workspaces/{wid}/channels/{cid}/messages/{mid}/reactions")
async def list_reactions_endpoint(
    cid: UUID,
    mid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_see_message(db, user_id=ctx.user.id, message_id=mid):
        raise NotFound("message", str(mid))
    reactions = await list_reactions_for_message(db, message_id=mid)
    return {"reactions": reactions}
