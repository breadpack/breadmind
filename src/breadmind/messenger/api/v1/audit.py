from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.service.audit_service import list_audit


router = APIRouter(tags=["audit"])


class AuditEntryResp(BaseModel):
    actor_user_id: Optional[UUID]
    workspace_id: UUID
    entity_kind: str
    entity_id: Optional[UUID]
    action: str
    payload: dict
    ip_address: Optional[str]
    user_agent: Optional[str]
    occurred_at: datetime


class AuditListResp(BaseModel):
    entries: list[AuditEntryResp]


@router.get("/workspaces/{wid}/audit-log", response_model=AuditListResp)
async def get_audit(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    actor: Optional[UUID] = None,
    entity_kind: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if ctx.user.role not in ("owner", "admin"):
        raise Forbidden("admin only")
    rows = await list_audit(
        db, workspace_id=ctx.workspace_id,
        since=since, until=until, actor=actor,
        entity_kind=entity_kind, limit=limit,
    )
    return AuditListResp(entries=[AuditEntryResp(**asdict(r)) for r in rows])
