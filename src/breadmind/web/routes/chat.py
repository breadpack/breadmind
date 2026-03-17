"""Chat and session management routes."""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def setup_chat_routes(r: APIRouter, app_state):
    """Register chat and session routes."""

    @r.get("/api/sessions")
    async def list_sessions():
        if app_state._working_memory:
            return {"sessions": await app_state._working_memory.list_all_sessions(user="web")}
        return {"sessions": []}

    @r.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        if app_state._working_memory:
            return {"messages": app_state._working_memory.get_session_messages(f"web:{session_id}")}
        return {"messages": []}

    @r.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if app_state._working_memory:
            app_state._working_memory.clear_session(f"web:{session_id}")
        return {"status": "ok"}

    @r.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        # Auth check for WebSocket — extract and store token for re-validation
        session_token = None
        if app_state._auth and app_state._auth.enabled:
            # Extract token from query param or cookie (same logic as authenticate_websocket)
            token = websocket.query_params.get("token", "")
            if token and app_state._auth.verify_session(token):
                session_token = token
            else:
                token = websocket.cookies.get("breadmind_session", "")
                if token and app_state._auth.verify_session(token):
                    session_token = token

            if not session_token:
                await websocket.close(code=4001, reason="Authentication required")
                return

        await websocket.accept()
        async with app_state._lock:
            app_state._connections.append(websocket)
        current_session = "default"
        try:
            while True:
                data = await websocket.receive_text()

                # Re-validate session on every message to catch expiration
                if session_token and app_state._auth and app_state._auth.enabled:
                    if not app_state._auth.verify_session(session_token):
                        await websocket.close(code=4001, reason="Session expired")
                        return
                msg = json.loads(data)

                # Handle session switching
                if msg.get("type") == "switch_session":
                    current_session = msg.get("session_id", "default")
                    # Try loading from DB if not in memory
                    if app_state._working_memory and app_state._working_memory._db:
                        sid = f"web:{current_session}"
                        if sid not in app_state._working_memory._sessions:
                            await app_state._working_memory.load_session_from_db(sid)
                    # Send session history
                    if app_state._working_memory:
                        messages = app_state._working_memory.get_session_messages(f"web:{current_session}")
                        await websocket.send_text(json.dumps({
                            "type": "session_history",
                            "session_id": current_session,
                            "messages": messages,
                        }))
                    continue

                if msg.get("type") == "new_session":
                    import uuid
                    current_session = str(uuid.uuid4())[:8]
                    await websocket.send_text(json.dumps({
                        "type": "session_created",
                        "session_id": current_session,
                    }))
                    continue

                user_message = msg.get("message", "")
                # Use session ID directly as channel to avoid
                # nested "web:web:web:..." from user:channel concatenation
                channel = current_session

                if app_state._message_handler:
                    # Auto-title: use first message as title
                    sid = f"web:{current_session}"
                    if app_state._working_memory:
                        session = app_state._working_memory.get_or_create_session(
                            sid, user="web", channel=channel,
                        )
                        if not session.metadata.get("title") and user_message:
                            app_state._working_memory.set_session_title(
                                sid,
                                user_message[:50],
                            )

                    # Set up progress callback for real-time status
                    async def _progress(status: str, detail: str = ""):
                        try:
                            await websocket.send_text(json.dumps({
                                "type": "progress",
                                "status": status,
                                "detail": detail,
                                "session_id": current_session,
                            }))
                        except Exception:
                            pass

                    if app_state._agent and hasattr(app_state._agent, "set_progress_callback"):
                        app_state._agent.set_progress_callback(_progress)

                    try:
                        if asyncio.iscoroutinefunction(app_state._message_handler):
                            response = await app_state._message_handler(user_message, user="web", channel=channel)
                        else:
                            response = app_state._message_handler(user_message, user="web", channel=channel)
                    finally:
                        if app_state._agent and hasattr(app_state._agent, "set_progress_callback"):
                            app_state._agent.set_progress_callback(None)
                else:
                    response = "No message handler configured."

                await websocket.send_text(json.dumps({
                    "type": "response",
                    "message": response,
                    "session_id": current_session,
                }))
        except WebSocketDisconnect:
            async with app_state._lock:
                if websocket in app_state._connections:
                    app_state._connections.remove(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            async with app_state._lock:
                if websocket in app_state._connections:
                    app_state._connections.remove(websocket)
