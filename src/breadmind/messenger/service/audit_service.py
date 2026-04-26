from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor_user_id: Optional[UUID]
    workspace_id: UUID
    entity_kind: str
    entity_id: Optional[UUID]
    action: str
    payload: dict
    ip_address: Optional[str]
    user_agent: Optional[str]
    occurred_at: datetime


async def write_audit(
    db, *,
    workspace_id: UUID, entity_kind: str, action: str,
    actor_user_id: UUID | None = None, entity_id: UUID | None = None,
    payload: dict | None = None, ip: str | None = None, ua: str | None = None,
) -> None:
    # The core audit_log table has legacy columns (result, params) that must be satisfied.
    # result NOT NULL — use empty string as sentinel for messenger-originated entries.
    await db.execute(
        """INSERT INTO audit_log
              (action, result, workspace_id, actor_user_id, entity_kind, entity_id,
               payload, ip_address, user_agent, occurred_at)
           VALUES ($1, '', $2, $3, $4, $5, $6::jsonb, $7, $8, now())""",
        action, workspace_id, actor_user_id, entity_kind, entity_id,
        json.dumps(payload or {}), ip, ua,
    )


async def list_audit(
    db, *, workspace_id: UUID, since=None, until=None,
    actor: UUID | None = None, entity_kind: str | None = None, limit: int = 100,
) -> list[AuditEntry]:
    where = ["workspace_id = $1"]
    args: list = [workspace_id]
    if since is not None:
        args.append(since)
        where.append(f"occurred_at >= ${len(args)}")
    if until is not None:
        args.append(until)
        where.append(f"occurred_at <= ${len(args)}")
    if actor is not None:
        args.append(actor)
        where.append(f"actor_user_id = ${len(args)}")
    if entity_kind is not None:
        args.append(entity_kind)
        where.append(f"entity_kind = ${len(args)}")
    args.append(limit)
    rows = await db.fetch(
        "SELECT actor_user_id, workspace_id, entity_kind, entity_id, action, payload, "
        "ip_address::text AS ip_address, user_agent, occurred_at "
        f"FROM audit_log WHERE {' AND '.join(where)} ORDER BY occurred_at DESC LIMIT ${len(args)}",
        *args,
    )
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        out.append(AuditEntry(**d))
    return out
