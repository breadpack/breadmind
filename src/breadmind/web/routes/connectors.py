"""Admin routes to register and manage ingestion connector configs.

.. note::
   Write endpoints (POST/PATCH/DELETE) are guarded by a minimal
   ``x-admin-token`` header check — the expected value is read from the
   ``BREADMIND_ADMIN_TOKEN`` env var at request time. If the env var is
   unset the endpoints return ``503`` so that an unconfigured deployment
   cannot be modified anonymously. Production deployments SHOULD replace
   this with a proper auth middleware (session/JWT/SSO) — the header
   check is a P5 ops-readiness stop-gap, not a long-term solution.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from breadmind.web.dependencies import get_db

logger = logging.getLogger(__name__)

_ALLOWED_CONNECTORS = {"confluence"}
_ADMIN_TOKEN_ENV = "BREADMIND_ADMIN_TOKEN"


def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Minimal admin-token guard for connector write endpoints.

    Reads ``BREADMIND_ADMIN_TOKEN`` at request time (not import time) so
    tests can set/clear the env var via ``monkeypatch.setenv``. Returns
    ``503`` when the env var is unset (i.e. deployment has not opted in),
    ``401`` when the header is missing or does not match.
    """
    expected = os.environ.get(_ADMIN_TOKEN_ENV, "")
    if not expected:
        raise HTTPException(
            503,
            f"admin auth not configured ({_ADMIN_TOKEN_ENV} unset)",
        )
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(401, "invalid or missing admin token")


class _RegisterBody(BaseModel):
    connector: str = Field(..., examples=["confluence"])
    project_id: uuid.UUID
    scope_key: str
    settings: dict
    enabled: bool = True


class _PatchBody(BaseModel):
    enabled: bool | None = None


def _build_store(db: Any):
    from breadmind.kb.connectors.configs_store import ConnectorConfigsStore
    return ConnectorConfigsStore(db)


async def _reload_beat(db: Any) -> None:
    from breadmind.kb.connectors.schedule import reload_beat_schedule_from_db
    await reload_beat_schedule_from_db(db)


async def _safe_reload_beat(db: Any) -> None:
    """Best-effort Beat schedule reload after a DB write.

    If Redis/Beat is down the CRUD row has still been committed, so we
    swallow the failure with a log line rather than bubble a 500. The
    ``@beat_init`` handler (B14) will re-read the schedule on the next
    Beat restart, so durable state stays consistent.
    """
    try:
        await _reload_beat(db)
    except Exception:  # noqa: BLE001 — best-effort; see docstring
        logger.exception(
            "reload_beat_schedule_from_db failed; row persisted, "
            "schedule will refresh on next Beat restart",
        )


def setup_connectors_routes(app, app_state) -> None:
    router = APIRouter(prefix="/api/connectors", tags=["connectors"])

    def _row_to_dict(row) -> dict:
        return {
            "id": str(row.id),
            "connector": row.connector,
            "project_id": str(row.project_id),
            "scope_key": row.scope_key,
            "settings": row.settings,
            "enabled": bool(row.enabled),
        }

    @router.get("")
    async def list_configs(db=Depends(get_db)):
        store = _build_store(db)
        rows = await store.list()
        return {"configs": [_row_to_dict(r) for r in rows]}

    @router.post("", status_code=201, dependencies=[Depends(_require_admin)])
    async def register(body: _RegisterBody, db=Depends(get_db)):
        if body.connector not in _ALLOWED_CONNECTORS:
            raise HTTPException(400, f"Unknown connector: {body.connector}")
        settings = body.settings or {}
        if body.connector == "confluence":
            missing = [k for k in ("base_url", "credentials_ref")
                       if not settings.get(k)]
            if missing:
                raise HTTPException(
                    400, f"Missing required settings: {', '.join(missing)}"
                )
            base_url = str(settings.get("base_url") or "")
            if not base_url.lower().startswith("https://"):
                raise HTTPException(
                    400, "base_url must use https://",
                )
        store = _build_store(db)
        row = await store.register(
            connector=body.connector,
            project_id=body.project_id,
            scope_key=body.scope_key,
            settings=settings,
            enabled=body.enabled,
        )
        await _safe_reload_beat(db)
        return _row_to_dict(row)

    @router.patch("/{config_id}", dependencies=[Depends(_require_admin)])
    async def patch(config_id: uuid.UUID, body: _PatchBody, db=Depends(get_db)):
        if body.enabled is None:
            raise HTTPException(400, "enabled is required")
        store = _build_store(db)
        await store.set_enabled(config_id, body.enabled)
        await _safe_reload_beat(db)
        return {"id": str(config_id), "enabled": body.enabled}

    @router.delete(
        "/{config_id}", status_code=204,
        dependencies=[Depends(_require_admin)],
    )
    async def delete(config_id: uuid.UUID, db=Depends(get_db)):
        store = _build_store(db)
        await store.delete(config_id)
        await _safe_reload_beat(db)
        return Response(status_code=204)

    app.include_router(router)
