"""Browser session management and live view routes."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


def _get_engine(app_state) -> Any | None:
    """Get BrowserEngine from app state."""
    try:
        container = getattr(app_state, "_container", None)
        if container:
            return container.get("browser_engine")
    except Exception:
        pass
    # Try via plugin
    try:
        plugin_mgr = getattr(app_state, "_plugin_manager", None)
        if plugin_mgr:
            for p in plugin_mgr._plugins.values():
                engine = getattr(p, "_engine", None)
                if engine and hasattr(engine, "_session_mgr"):
                    return engine
    except Exception:
        pass
    return None


def setup_browser_routes(app, app_state):
    """Register browser management and live view routes."""

    @app.get("/api/browser/sessions")
    async def list_sessions():
        engine = _get_engine(app_state)
        if not engine:
            return JSONResponse({"error": "Browser engine not available"}, status_code=503)
        sessions = engine._session_mgr.list_sessions()
        return {"sessions": sessions}

    @app.post("/api/browser/sessions")
    async def create_session(request: Request):
        engine = _get_engine(app_state)
        if not engine:
            return JSONResponse({"error": "Browser engine not available"}, status_code=503)
        data = await request.json()
        try:
            result = await engine.handle_session(
                action="create",
                name=data.get("name", ""),
                mode=data.get("mode", "playwright"),
                persistent=data.get("persistent", False),
                cdp_url=data.get("cdp_url", ""),
            )
            return {"status": "ok", "message": result}
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.delete("/api/browser/sessions/{session_id}")
    async def close_session(session_id: str):
        engine = _get_engine(app_state)
        if not engine:
            return JSONResponse({"error": "Browser engine not available"}, status_code=503)
        result = await engine.handle_session(action="close", session=session_id)
        if "[error]" in result:
            return JSONResponse({"error": result}, status_code=404)
        return {"status": "ok", "message": result}

    @app.post("/api/browser/sessions/close-all")
    async def close_all_sessions():
        engine = _get_engine(app_state)
        if not engine:
            return JSONResponse({"error": "Browser engine not available"}, status_code=503)
        result = await engine.handle_session(action="close_all")
        return {"status": "ok", "message": result}

    @app.get("/api/browser/macros")
    async def list_macros():
        engine = _get_engine(app_state)
        if not engine or not engine._macro_tools:
            return {"macros": []}
        store = engine._macro_store
        if not store:
            return {"macros": []}
        return {"macros": [m.to_dict() for m in store.list_all()]}

    @app.post("/api/browser/macros/{macro_id}/execute")
    async def execute_macro(macro_id: str, request: Request):
        engine = _get_engine(app_state)
        if not engine or not engine._macro_tools:
            return JSONResponse({"error": "Macro system not available"}, status_code=503)
        data = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        session = data.get("session", "")
        result = await engine._macro_tools.play(macro_id=macro_id, session=session)
        return {"status": "ok", "result": result}

    @app.websocket("/ws/browser/live")
    async def websocket_live_view(websocket: WebSocket):
        """WebSocket endpoint for live browser screenshot streaming via CDP screencast."""
        engine = _get_engine(app_state)
        if not engine:
            await websocket.close(code=4003, reason="Browser engine not available")
            return

        await websocket.accept()
        session_id = None
        cdp_session = None
        streaming = False
        frame_queue: asyncio.Queue = asyncio.Queue(maxsize=10)

        def on_screencast_frame(params):
            """CDP event handler for incoming screencast frames."""
            try:
                frame_queue.put_nowait(params)
            except asyncio.QueueFull:
                pass  # Drop frame if queue is full

        try:
            while True:
                msg_text = await websocket.receive_text()
                msg = json.loads(msg_text)
                msg_type = msg.get("type", "")

                if msg_type == "start":
                    session_id = msg.get("session_id", "")
                    fps = min(max(msg.get("fps", 2), 1), 5)
                    interval = 1.0 / fps

                    session = engine._session_mgr.get(session_id)
                    if not session:
                        session = engine._session_mgr.get_by_name(session_id)
                    if not session:
                        await websocket.send_text(json.dumps({
                            "type": "error", "message": f"Session not found: {session_id}",
                        }))
                        continue

                    # Start CDP screencast
                    from breadmind.tools.browser import get_cdp_session
                    cdp_session = await get_cdp_session(session.page)
                    cdp_session.on("Page.screencastFrame", on_screencast_frame)
                    await cdp_session.send("Page.startScreencast", {
                        "format": "png",
                        "quality": 80,
                        "maxWidth": 1280,
                        "maxHeight": 900,
                        "everyNthFrame": 1,
                    })
                    streaming = True

                    await websocket.send_text(json.dumps({
                        "type": "started",
                        "session_id": session.id,
                        "session_name": session.name,
                    }))

                    # Stream frames in background
                    async def stream_frames():
                        while streaming:
                            try:
                                params = await asyncio.wait_for(frame_queue.get(), timeout=interval)
                                data = params.get("data", "")
                                metadata = params.get("metadata", {})
                                session_id_val = params.get("sessionId", 0)

                                await websocket.send_text(json.dumps({
                                    "type": "frame",
                                    "data": data,
                                    "timestamp": metadata.get("timestamp", 0),
                                }))

                                # Acknowledge frame to CDP
                                if cdp_session:
                                    await cdp_session.send("Page.screencastFrameAck", {
                                        "sessionId": session_id_val,
                                    })
                            except asyncio.TimeoutError:
                                continue
                            except Exception:
                                break

                    asyncio.create_task(stream_frames())

                elif msg_type == "stop":
                    streaming = False
                    if cdp_session:
                        try:
                            await cdp_session.send("Page.stopScreencast", {})
                        except Exception:
                            pass
                    await websocket.send_text(json.dumps({"type": "stopped"}))

                elif msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("Browser live view WebSocket error: %s", e)
        finally:
            streaming = False
            if cdp_session:
                try:
                    await cdp_session.send("Page.stopScreencast", {})
                except Exception:
                    pass
