# src/breadmind/messenger/api/v1/scheduled.py
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import get_db, get_workspace_context, WorkspaceContext
from breadmind.messenger.service.scheduled_service import (
    ScheduledMessageRow,
    schedule_message,
    list_scheduled,
    cancel_scheduled,
)

router = APIRouter(tags=["scheduled"])


class ScheduleMessageReq(BaseModel):
    channel_id: UUID
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None
    scheduled_for: datetime


class ScheduledMessageResp(BaseModel):
    id: UUID
    workspace_id: UUID
    channel_id: UUID
    author_id: UUID
    text: Optional[str]
    blocks: list
    scheduled_for: datetime
    created_at: datetime
    sent_message_id: Optional[UUID]
    cancelled_at: Optional[datetime]


def _to_resp(row: ScheduledMessageRow) -> ScheduledMessageResp:
    return ScheduledMessageResp(**asdict(row))


@router.post(
    "/workspaces/{wid}/scheduled-messages",
    response_model=ScheduledMessageResp,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_message_endpoint(
    body: ScheduleMessageReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    row = await schedule_message(
        db,
        workspace_id=ctx.workspace_id,
        channel_id=body.channel_id,
        author_id=ctx.user.id,
        text=body.text,
        blocks=body.blocks,
        scheduled_for=body.scheduled_for,
    )
    return _to_resp(row)


@router.get("/workspaces/{wid}/scheduled-messages")
async def list_scheduled_endpoint(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_scheduled(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user.id,
    )
    return {"scheduled": [_to_resp(r).model_dump() for r in rows]}


@router.delete(
    "/workspaces/{wid}/scheduled-messages/{sid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scheduled_endpoint(
    sid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    await cancel_scheduled(db, scheduled_id=sid, user_id=ctx.user.id)
