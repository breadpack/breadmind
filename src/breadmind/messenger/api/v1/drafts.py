from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.service.draft_service import (
    upsert_draft, list_drafts, delete_draft,
)


router = APIRouter(tags=["drafts"])


class DraftReq(BaseModel):
    channel_id: UUID
    thread_parent_id: Optional[UUID] = None
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None


class DraftResp(BaseModel):
    user_id: UUID
    channel_id: UUID
    thread_parent_id: Optional[UUID]
    text: Optional[str]
    blocks: list
    updated_at: datetime


class DraftsListResp(BaseModel):
    drafts: list[DraftResp]


@router.put("/workspaces/{wid}/drafts", status_code=204)
async def upsert_draft_endpoint(
    body: DraftReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    await upsert_draft(
        db, user_id=ctx.user.id, channel_id=body.channel_id,
        thread_parent_id=body.thread_parent_id, text=body.text, blocks=body.blocks,
    )


@router.get("/workspaces/{wid}/drafts", response_model=DraftsListResp)
async def list_drafts_endpoint(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_drafts(db, user_id=ctx.user.id, workspace_id=ctx.workspace_id)
    return DraftsListResp(drafts=[DraftResp(**asdict(r)) for r in rows])


@router.delete("/workspaces/{wid}/drafts", status_code=204)
async def delete_draft_endpoint(
    body: DraftReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    await delete_draft(
        db, user_id=ctx.user.id, channel_id=body.channel_id,
        thread_parent_id=body.thread_parent_id,
    )
