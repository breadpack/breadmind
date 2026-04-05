"""Conversation and agent config export/import API routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


def setup_export_routes(app, app_state):
    """Register export/import routes on the FastAPI app."""

    # ── helpers ─────────────────────────────────────────────────────

    def _conversation_store():
        """Resolve ConversationStore from app_state or return None."""
        # Try common attribute names
        for attr in ("_conversation_store", "conversation_store"):
            store = getattr(app_state, attr, None)
            if store is not None:
                return store
        return None

    def _agent():
        return getattr(app_state, "_agent", None)

    # ── Conversation export ────────────────────────────────────────

    @app.get("/api/conversations/{session_id}/export")
    async def export_conversation(session_id: str, format: str = "json"):
        from breadmind.core.exporter import ConversationExporter

        store = _conversation_store()
        if store is None:
            return JSONResponse(503, {"error": "Conversation store not available"})

        messages = await store.load_conversation(session_id)
        if messages is None:
            return JSONResponse(404, {"error": f"Conversation {session_id} not found"})

        metadata = {"session_id": session_id}

        if format == "markdown":
            content = ConversationExporter.to_markdown(messages, metadata)
            return Response(
                content=content,
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="conversation-{session_id}.md"',
                },
            )

        # Default: JSON
        content = ConversationExporter.to_json(messages, metadata)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="conversation-{session_id}.json"',
            },
        )

    # ── Conversation import ────────────────────────────────────────

    @app.post("/api/conversations/import")
    async def import_conversation(request):
        from breadmind.core.exporter import ConversationExporter
        from breadmind.plugins.builtin.memory.conversation_store import (
            ConversationMeta,
        )

        store = _conversation_store()
        if store is None:
            return JSONResponse(503, {"error": "Conversation store not available"})

        try:
            body = await request.body()
            data = body.decode("utf-8")
        except Exception as exc:
            return JSONResponse(400, {"error": f"Failed to read request body: {exc}"})

        try:
            messages, metadata = ConversationExporter.from_json(data)
        except ValueError as exc:
            return JSONResponse(400, {"error": str(exc)})

        session_id = metadata.get("session_id")
        if not session_id:
            return JSONResponse(400, {"error": "metadata.session_id is required"})

        meta = ConversationMeta(
            session_id=session_id,
            user=metadata.get("user", "imported"),
            title=metadata.get("title", "Imported conversation"),
            message_count=len(messages),
        )

        await store.save_conversation(session_id, messages, meta)

        return {"status": "ok", "session_id": session_id, "message_count": len(messages)}

    # ── Agent config export ────────────────────────────────────────

    @app.get("/api/agent/config/export")
    async def export_agent_config():
        from breadmind.core.exporter import AgentConfigExporter

        agent = _agent()
        if agent is None:
            return JSONResponse(503, {"error": "Agent not available"})

        try:
            yaml_content = AgentConfigExporter.to_yaml(agent)
        except Exception as exc:
            logger.exception("Failed to export agent config")
            return JSONResponse(500, {"error": f"Export failed: {exc}"})

        return Response(
            content=yaml_content,
            media_type="text/yaml; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="agent-config.yaml"',
            },
        )
