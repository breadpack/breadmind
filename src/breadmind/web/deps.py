"""Shared FastAPI dependencies - current user identification."""
from __future__ import annotations

import os
from dataclasses import dataclass
from fastapi import HTTPException, Request
from breadmind.web.auth import AuthManager


_auth: AuthManager | None = None


def set_auth_manager(manager: AuthManager) -> None:
    global _auth
    _auth = manager


@dataclass(frozen=True)
class CurrentUser:
    username: str
    is_admin: bool


def _extract_token(request: Request) -> str | None:
    tok = request.cookies.get("breadmind_session")
    if tok:
        return tok
    auth_h = request.headers.get("authorization", "")
    if auth_h.startswith("Bearer "):
        return auth_h[7:]
    return None


def get_current_user(request: Request) -> CurrentUser:
    if _auth is None or not getattr(_auth, "enabled", False):
        return CurrentUser(username="local", is_admin=True)
    token = _extract_token(request)
    username = _auth.get_session_username(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="login required")
    admins = {a.strip() for a in os.environ.get("BREADMIND_ADMIN_USERS", "").split(",")}
    admins.discard("")
    return CurrentUser(username=username, is_admin=username in admins)
