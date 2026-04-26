# src/breadmind/messenger/api/v1/dms.py
from __future__ import annotations
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import get_db, get_workspace_context, WorkspaceContext
from breadmind.messenger.api.v1.channels import ChannelResp
from breadmind.messenger.service.dm_service import open_dm_or_mpdm, list_dms_for_user

router = APIRouter(tags=["dms"])


class OpenDmReq(BaseModel):
    user_ids: list[UUID]


@router.post("/workspaces/{wid}/dms")
async def open_dm_endpoint(
    body: OpenDmReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    channel, created = await open_dm_or_mpdm(
        db,
        workspace_id=ctx.workspace_id,
        opener_id=ctx.user.id,
        member_ids=body.user_ids,
    )
    resp = ChannelResp(**asdict(channel))
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    from fastapi.responses import JSONResponse
    return JSONResponse(content=resp.model_dump(mode="json"), status_code=status_code)


@router.get("/workspaces/{wid}/dms")
async def list_dms_endpoint(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_dms_for_user(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user.id,
    )
    return {"dms": [ChannelResp(**asdict(r)).model_dump() for r in rows]}
