from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.events import HookEvent
from breadmind.hooks.trace import get_trace_buffer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hooks"])


class HookOverrideIn(BaseModel):
    hook_id: str
    event: str
    type: str
    tool_pattern: str | None = None
    priority: int = 0
    enabled: bool = True
    config_json: dict = {}
    source: str | None = "user"
    command: str | None = None
    timeout_sec: float | None = None


def _get_registry(request: Request):
    reg = getattr(request.app.state, "hook_registry", None)
    if reg is None:
        raise HTTPException(500, "HookRegistry not configured")
    return reg


@router.get("/api/hooks/list")
async def list_hooks(request: Request):
    reg = _get_registry(request)
    try:
        await reg.reload()
    except Exception as e:
        logger.warning("HookRegistry reload failed: %s", e)

    manifest_hooks = [
        {
            "hook_id": h.name,
            "event": h.event.value,
            "type": h.__class__.__name__.lower().replace("hook", ""),
            "tool_pattern": getattr(h, "tool_pattern", None),
            "priority": getattr(h, "priority", 0),
            "timeout_sec": getattr(h, "timeout_sec", 0),
            "enabled": True,
            "source": "manifest",
            "config": {},
        }
        for h in reg._manifest.values()
    ]

    db_rows = await reg.store.list_all()
    manifest_ids = {h["hook_id"] for h in manifest_hooks}
    db_hooks = []
    for ov in db_rows:
        if ov.hook_id in manifest_ids:
            for m in manifest_hooks:
                if m["hook_id"] == ov.hook_id:
                    m["has_override"] = True
                    m["override_enabled"] = ov.enabled
                    m["override_priority"] = ov.priority
            continue
        db_hooks.append({
            "hook_id": ov.hook_id,
            "event": ov.event,
            "type": ov.type,
            "tool_pattern": ov.tool_pattern,
            "priority": ov.priority,
            "timeout_sec": (ov.config_json or {}).get("timeout_sec"),
            "enabled": ov.enabled,
            "source": "db",
            "config": ov.config_json or {},
        })

    all_hooks = manifest_hooks + db_hooks
    return {"total": len(all_hooks), "hooks": all_hooks}


@router.post("/api/hooks/")
async def create_hook(request: Request, body: HookOverrideIn):
    reg = _get_registry(request)
    try:
        HookEvent(body.event)
    except ValueError:
        raise HTTPException(400, f"Unknown event: {body.event}")
    if body.type not in {"shell", "python"}:
        raise HTTPException(400, f"Unsupported type: {body.type}")

    cfg = dict(body.config_json)
    if body.command and "command" not in cfg:
        cfg["command"] = body.command
    if body.timeout_sec is not None and "timeout_sec" not in cfg:
        cfg["timeout_sec"] = body.timeout_sec

    ov = HookOverride(
        hook_id=body.hook_id,
        source=body.source,
        event=body.event,
        type=body.type,
        tool_pattern=body.tool_pattern,
        priority=body.priority,
        enabled=body.enabled,
        config_json=cfg,
    )
    await reg.store.insert(ov)
    try:
        await reg.reload()
    except Exception:
        pass
    return {"status": "ok", "hook_id": body.hook_id}


@router.put("/api/hooks/{hook_id}")
async def update_hook(hook_id: str, request: Request, body: HookOverrideIn):
    reg = _get_registry(request)
    await reg.store.delete(hook_id)
    cfg = dict(body.config_json)
    if body.command and "command" not in cfg:
        cfg["command"] = body.command
    if body.timeout_sec is not None and "timeout_sec" not in cfg:
        cfg["timeout_sec"] = body.timeout_sec
    ov = HookOverride(
        hook_id=hook_id,
        source=body.source,
        event=body.event,
        type=body.type,
        tool_pattern=body.tool_pattern,
        priority=body.priority,
        enabled=body.enabled,
        config_json=cfg,
    )
    await reg.store.insert(ov)
    try:
        await reg.reload()
    except Exception:
        pass
    return {"status": "ok", "hook_id": hook_id}


@router.delete("/api/hooks/{hook_id}")
async def delete_hook(hook_id: str, request: Request):
    reg = _get_registry(request)
    if hook_id in reg._manifest:
        raise HTTPException(400, "Cannot delete manifest hook — disable via override instead")
    await reg.store.delete(hook_id)
    try:
        await reg.reload()
    except Exception:
        pass
    return {"status": "ok"}


@router.get("/api/hooks/traces")
async def list_traces(
    limit: int = 100, event: str | None = None, hook_id: str | None = None,
):
    buf = get_trace_buffer()
    entries = buf.recent(limit=limit, event=event, hook_id=hook_id)
    return {"total": len(entries), "entries": [e.to_dict() for e in entries]}


@router.get("/api/hooks/stats")
async def hook_stats():
    return {"stats": get_trace_buffer().stats()}


@router.websocket("/ws/hooks/traces")
async def ws_trace_stream(websocket: WebSocket):
    await websocket.accept()
    buf = get_trace_buffer()
    queue: asyncio.Queue = asyncio.Queue()
    buf.subscribe(queue)
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json(entry.to_dict())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("ws_trace_stream error: %s", e)
    finally:
        buf.unsubscribe(queue)
