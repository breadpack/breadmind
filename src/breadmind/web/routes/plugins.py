"""Plugin management routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import get_app_state, get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plugins"])


# --- Plugin Management ---

@router.get("/api/plugins")
async def list_plugins(app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return {"plugins": []}
    manifests = await app._plugin_mgr.discover()
    result = []
    for m in manifests:
        info = await app._plugin_mgr._registry.get(m.name)
        result.append({
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "author": m.author,
            "enabled": info.get("enabled", True) if info else True,
            "loaded": m.name in app._plugin_mgr.loaded_plugins,
        })
    return {"plugins": result}


@router.post("/api/plugins/install")
async def install_plugin(request: Request, app=Depends(get_app_state)):
    data = await request.json()
    source = data.get("source", "")
    if not source:
        return JSONResponse({"error": "source is required"}, status_code=400)
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return JSONResponse({"error": "Plugin system not initialized"}, status_code=500)
    try:
        manifest = await app._plugin_mgr.install(source)
        return {"status": "ok", "plugin": {"name": manifest.name, "version": manifest.version}}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/plugins/{name}/enable")
async def enable_plugin(name: str, app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return JSONResponse({"error": "Plugin system not initialized"}, status_code=500)
    await app._plugin_mgr._registry.set_enabled(name, True)
    await app._plugin_mgr.load(name)
    return {"status": "ok"}


@router.post("/api/plugins/{name}/disable")
async def disable_plugin(name: str, app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return JSONResponse({"error": "Plugin system not initialized"}, status_code=500)
    await app._plugin_mgr.unload(name)
    await app._plugin_mgr._registry.set_enabled(name, False)
    return {"status": "ok"}


@router.delete("/api/plugins/{name}")
async def uninstall_plugin(name: str, app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return JSONResponse({"error": "Plugin system not initialized"}, status_code=500)
    await app._plugin_mgr.uninstall(name)
    return {"status": "ok"}


@router.get("/api/plugins/{name}/settings")
async def get_plugin_settings(name: str, app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return {"settings": {}}
    return {"settings": app._plugin_mgr.get_settings(name)}


@router.post("/api/plugins/{name}/settings")
async def update_plugin_settings(name: str, request: Request, app=Depends(get_app_state), db=Depends(get_db)):
    data = await request.json()
    if db:
        await db.set_setting(f"plugin_settings:{name}", data)
    return {"status": "ok"}


# --- Marketplace ---

@router.get("/api/marketplace/search")
async def marketplace_search(q: str = "", tags: str = "", app=Depends(get_app_state)):
    if not hasattr(app, '_marketplace') or not app._marketplace:
        from breadmind.plugins.marketplace import MarketplaceClient
        app._marketplace = MarketplaceClient()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = await app._marketplace.search(q, tag_list)
    return {"results": results}


@router.post("/api/marketplace/install/{name}")
async def marketplace_install(name: str, app=Depends(get_app_state)):
    if not hasattr(app, '_plugin_mgr') or not app._plugin_mgr:
        return JSONResponse({"error": "Plugin system not initialized"}, status_code=500)
    if not hasattr(app, '_marketplace') or not app._marketplace:
        from breadmind.plugins.marketplace import MarketplaceClient
        app._marketplace = MarketplaceClient()
    try:
        target = await app._marketplace.install(name, app._plugin_mgr._plugins_dir)
        manifest = await app._plugin_mgr.load_from_directory(target)
        return {"status": "ok", "plugin": {"name": manifest.name if manifest else name}}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
