"""Admin routes to register and manage ingestion connector configs."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from breadmind.web.dependencies import get_db

logger = logging.getLogger(__name__)

_ALLOWED_CONNECTORS = {"confluence"}


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

    @router.post("", status_code=201)
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
        store = _build_store(db)
        row = await store.register(
            connector=body.connector,
            project_id=body.project_id,
            scope_key=body.scope_key,
            settings=settings,
            enabled=body.enabled,
        )
        await _reload_beat(db)
        return _row_to_dict(row)

    @router.patch("/{config_id}")
    async def patch(config_id: uuid.UUID, body: _PatchBody, db=Depends(get_db)):
        if body.enabled is None:
            raise HTTPException(400, "enabled is required")
        store = _build_store(db)
        await store.set_enabled(config_id, body.enabled)
        await _reload_beat(db)
        return {"id": str(config_id), "enabled": body.enabled}

    @router.delete("/{config_id}", status_code=204)
    async def delete(config_id: uuid.UUID, db=Depends(get_db)):
        store = _build_store(db)
        await store.delete(config_id)
        await _reload_beat(db)
        return Response(status_code=204)

    app.include_router(router)
