"""Chat and session management routes."""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from breadmind.web.dependencies import get_working_memory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ── Secure credential form submission ────────────────────────────────

class _FormField(BaseModel):
    name: str
    value: str
    type: str = "text"


class _SecureFormRequest(BaseModel):
    form_id: str
    fields: list[_FormField]
    submit_message: str = ""


class _SecureFormResponse(BaseModel):
    sanitized_message: str
    refs: dict[str, str]


@router.post("/api/vault/submit-form", response_model=_SecureFormResponse)
async def submit_secure_form(body: _SecureFormRequest, request: Request):
    """Store password-type fields in the vault, return a sanitized message.

    Non-secret fields are kept as-is in the message.  Secret fields are
    replaced with ``credential_ref:xxx`` tokens so that the chat message
    never contains plaintext passwords.
    """
    # Authentication check — same pattern as auth_middleware in app.py
    app_state = request.app.state.app_state
    auth = getattr(app_state, "_auth", None)
    if auth and auth.enabled and not auth.authenticate_request(request):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    vault = getattr(request.app.state, "credential_vault", None)
    refs: dict[str, str] = {}
    replacements: dict[str, str] = {}  # {field_name} -> display value

    for field in body.fields:
        if field.type == "password" and vault:
            cred_id = f"form:{body.form_id}:{field.name}"
            await vault.store(cred_id, field.value)
            ref = vault.make_ref(cred_id)
            refs[field.name] = ref
            replacements[field.name] = ref
        else:
            replacements[field.name] = field.value

    # Build the sanitized message
    if body.submit_message:
        message = body.submit_message
        for name, display in replacements.items():
            message = message.replace("{" + name + "}", display)
    else:
        parts = []
        for name, display in replacements.items():
            if display and not display.startswith("credential_ref:"):
                parts.append(f"{name}: {display}")
            elif display:
                parts.append(f"{name}: [secured]")
        message = ", ".join(parts)

    return _SecureFormResponse(sanitized_message=message, refs=refs)


def setup_chat_routes(r: APIRouter, app_state):
    """Register chat and session routes."""

    @r.get("/api/sessions")
    async def list_sessions(working_memory=Depends(get_working_memory)):
        if working_memory:
            return {"sessions": await working_memory.list_all_sessions(user="web")}
        return {"sessions": []}

    @r.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str, working_memory=Depends(get_working_memory)):
        if working_memory:
            return {"messages": working_memory.get_session_messages(f"web:{session_id}")}
        return {"messages": []}

    @r.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str, working_memory=Depends(get_working_memory)):
        if working_memory:
            working_memory.clear_session(f"web:{session_id}")
        return {"status": "ok"}

    @r.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        app = websocket.app.state.app_state
        # Auth check for WebSocket — extract and store token for re-validation
        session_token = None
        if app._auth and app._auth.enabled:
            # Extract token from query param or cookie (same logic as authenticate_websocket)
            token = websocket.query_params.get("token", "")
            if token and app._auth.verify_session(token):
                session_token = token
            else:
                token = websocket.cookies.get("breadmind_session", "")
                if token and app._auth.verify_session(token):
                    session_token = token

            if not session_token:
                await websocket.close(code=4001, reason="Authentication required")
                return

        await websocket.accept()
        async with app._lock:
            app._connections.append(websocket)
        current_session = "default"
        try:
            while True:
                data = await websocket.receive_text()

                # Re-validate session on every message to catch expiration
                if session_token and app._auth and app._auth.enabled:
                    if not app._auth.verify_session(session_token):
                        await websocket.close(code=4001, reason="Session expired")
                        return
                msg = json.loads(data)

                # Handle session switching
                if msg.get("type") == "switch_session":
                    current_session = msg.get("session_id", "default")
                    # Try loading from DB if not in memory
                    if app._working_memory and app._working_memory._db:
                        sid = f"web:{current_session}"
                        if sid not in app._working_memory._sessions:
                            await app._working_memory.load_session_from_db(sid)
                    # Send session history
                    if app._working_memory:
                        messages = app._working_memory.get_session_messages(f"web:{current_session}")
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

                if app._message_handler:
                    # Auto-title: use first message as title
                    sid = f"web:{current_session}"
                    if app._working_memory:
                        session = app._working_memory.get_or_create_session(
                            sid, user="web", channel=channel,
                        )
                        if not session.metadata.get("title") and user_message:
                            from breadmind.storage.credential_vault import CredentialVault
                            title = CredentialVault.sanitize_text(user_message[:50])
                            app._working_memory.set_session_title(
                                sid,
                                title,
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

                    if app._agent and hasattr(app._agent, "set_progress_callback"):
                        app._agent.set_progress_callback(_progress)

                    try:
                        if asyncio.iscoroutinefunction(app._message_handler):
                            response = await app._message_handler(user_message, user="web", channel=channel)
                        else:
                            response = app._message_handler(user_message, user="web", channel=channel)
                    finally:
                        if app._agent and hasattr(app._agent, "set_progress_callback"):
                            app._agent.set_progress_callback(None)
                else:
                    response = "No message handler configured."

                await websocket.send_text(json.dumps({
                    "type": "response",
                    "message": response,
                    "session_id": current_session,
                }))
        except WebSocketDisconnect:
            async with app._lock:
                if websocket in app._connections:
                    app._connections.remove(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            async with app._lock:
                if websocket in app._connections:
                    app._connections.remove(websocket)
