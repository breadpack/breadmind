"""FastAPI dependency injection for auth + workspace context."""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Path, Request

from breadmind.messenger.auth.paseto import (
    decode_access_token, PasetoError,
)
from breadmind.messenger.errors import Unauthorized, Forbidden


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    workspace_id: UUID
    role: str
    email: str
    kind: str


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace_id: UUID
    user: CurrentUser


async def get_db(request: Request):
    """Acquire connection from app.state.db_pool."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        yield conn


async def get_current_user(
    request: Request,
    db = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized("missing bearer token")
    token = authorization[len("Bearer "):]
    key_hex: str = request.app.state.paseto_key_hex
    try:
        claims = decode_access_token(key_hex, token)
    except PasetoError as e:
        raise Unauthorized(str(e)) from e
    row = await db.fetchrow(
        "SELECT id, workspace_id, role, email, kind, deactivated_at "
        "FROM workspace_users WHERE id = $1",
        claims.user_id,
    )
    if row is None:
        raise Unauthorized("user not found")
    if row["deactivated_at"] is not None:
        raise Unauthorized("user deactivated")
    return CurrentUser(
        id=row["id"],
        workspace_id=row["workspace_id"],
        role=row["role"],
        email=row["email"],
        kind=row["kind"],
    )


async def get_workspace_context(
    wid: UUID = Path(...),
    user: CurrentUser = Depends(get_current_user),
) -> WorkspaceContext:
    if wid != user.workspace_id:
        raise Forbidden("token does not grant access to this workspace")
    return WorkspaceContext(workspace_id=wid, user=user)


def require_role(*allowed: str):
    """Factory for role-gated endpoints. Returns a FastAPI dependency callable."""
    async def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise Forbidden(f"role {user.role} not allowed; need one of {allowed}")
        return user
    return dep
