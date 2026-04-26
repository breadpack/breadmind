from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from breadmind.messenger.errors import NotFound, Conflict, ValidationFailed
from breadmind.messenger.service.audit_service import write_audit


@dataclass(frozen=True, slots=True)
class WorkspaceRow:
    id: UUID
    name: str
    slug: str
    domain: str | None
    icon_url: str | None
    plan: str
    archived_at: datetime | None
    default_channel_id: UUID | None


async def create_workspace(
    db, *,
    name: str, slug: str, created_by: UUID | None = None,
    domain: str | None = None,
) -> WorkspaceRow:
    if not slug or not slug.replace("-", "").isalnum():
        raise ValidationFailed([{"field": "slug", "msg": "alphanumeric+hyphen only"}])
    wid = uuid4()
    try:
        row = await db.fetchrow(
            """INSERT INTO org_projects (id, name, slug, domain, plan, created_by)
               VALUES ($1, $2, $3, $4, 'free', $5)
               RETURNING id, name, slug, domain, icon_url, plan, archived_at, default_channel_id""",
            wid, name, slug, domain, created_by,
        )
    except asyncpg.UniqueViolationError as e:
        raise Conflict(f"slug '{slug}' already taken") from e
    await write_audit(
        db, workspace_id=wid, entity_kind="workspace",
        action="create", actor_user_id=created_by,
        entity_id=wid, payload={"name": name, "slug": slug},
    )
    return WorkspaceRow(**dict(row))


async def get_workspace(db, workspace_id: UUID) -> WorkspaceRow:
    row = await db.fetchrow(
        "SELECT id, name, slug, domain, icon_url, plan, archived_at, default_channel_id "
        "FROM org_projects WHERE id = $1", workspace_id,
    )
    if row is None:
        raise NotFound("workspace", str(workspace_id))
    return WorkspaceRow(**dict(row))


async def list_workspaces_for_user(db, user_email: str) -> list[WorkspaceRow]:
    rows = await db.fetch(
        """SELECT op.id, op.name, op.slug, op.domain, op.icon_url, op.plan,
                  op.archived_at, op.default_channel_id
           FROM org_projects op
           JOIN workspace_users wu ON wu.workspace_id = op.id
           WHERE wu.email = $1 AND wu.deactivated_at IS NULL""",
        user_email,
    )
    return [WorkspaceRow(**dict(r)) for r in rows]


async def update_workspace(
    db, workspace_id: UUID, *,
    name: str | None = None, icon_url: str | None = None, domain: str | None = None,
) -> WorkspaceRow:
    updates = []
    args: list = []
    if name is not None:
        updates.append(f"name = ${len(args) + 1}")
        args.append(name)
    if icon_url is not None:
        updates.append(f"icon_url = ${len(args) + 1}")
        args.append(icon_url)
    if domain is not None:
        updates.append(f"domain = ${len(args) + 1}")
        args.append(domain)
    if not updates:
        return await get_workspace(db, workspace_id)
    args.append(workspace_id)
    await db.execute(
        f"UPDATE org_projects SET {', '.join(updates)} WHERE id = ${len(args)}",
        *args,
    )
    return await get_workspace(db, workspace_id)
