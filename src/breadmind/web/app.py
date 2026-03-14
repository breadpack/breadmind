import asyncio
import json
import logging
from dataclasses import asdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Callable, Any

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, message_handler: Callable | None = None, tool_registry=None, mcp_manager=None,
                 config=None, monitoring_engine=None, safety_config=None,
                 agent=None, audit_logger=None, metrics_collector=None):
        self.app = FastAPI(title="BreadMind", version="0.1.0")
        self._message_handler = message_handler
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._config = config
        self._monitoring_engine = monitoring_engine
        self._safety_config = safety_config
        self._agent = agent
        self._audit_logger = audit_logger
        self._metrics_collector = metrics_collector
        self._connections: list[WebSocket] = []
        self._events: list[dict] = []
        self._lock = asyncio.Lock()
        self._setup_routes()

    async def on_monitoring_event(self, event):
        """Called by monitoring engine when an event occurs."""
        event_dict = {
            "source": event.source,
            "target": event.target,
            "severity": event.severity,
            "condition": event.condition,
            "details": event.details,
            "timestamp": event.timestamp.isoformat(),
        }
        self._events.append(event_dict)
        # Keep last 100 events
        if len(self._events) > 100:
            self._events = self._events[-100:]
        # Broadcast to connected WebSocket clients
        await self.broadcast_event(event_dict)

    async def broadcast_event(self, event_dict):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "monitoring_event", "event": event_dict}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)

    def _setup_routes(self):
        app = self.app

        @app.get("/health")
        async def health():
            agent_ok = self._message_handler is not None
            monitoring_ok = (
                self._monitoring_engine is not None
                and self._monitoring_engine.get_status()["running"]
            ) if self._monitoring_engine is not None else False

            components = {
                "agent": agent_ok,
                "monitoring": monitoring_ok,
            }

            # Agent is critical - if not configured, return 503
            if not agent_ok:
                return JSONResponse(
                    status_code=503,
                    content={"status": "degraded", "components": components},
                )

            return {"status": "ok", "components": components}

        @app.get("/api/tools")
        async def list_tools():
            if self._tool_registry:
                defs = self._tool_registry.get_all_definitions()
                return {"tools": [
                    {"name": d.name, "description": d.description, "source": self._tool_registry.get_tool_source(d.name)}
                    for d in defs
                ]}
            return {"tools": []}

        @app.get("/api/mcp/servers")
        async def list_mcp_servers():
            if self._mcp_manager:
                servers = await self._mcp_manager.list_servers()
                return {"servers": [
                    {"name": s.name, "transport": s.transport, "status": s.status, "tools": s.tools, "source": s.source}
                    for s in servers
                ]}
            return {"servers": []}

        @app.get("/", response_class=HTMLResponse)
        async def index():
            html_path = Path(__file__).parent / "static" / "index.html"
            if html_path.exists():
                return html_path.read_text(encoding="utf-8")
            return "<html><body><h1>BreadMind</h1><p>Static files not found.</p></body></html>"

        @app.get("/api/config")
        async def get_config():
            if self._config:
                return {
                    "llm": {
                        "default_provider": self._config.llm.default_provider,
                        "default_model": self._config.llm.default_model,
                        "tool_call_max_turns": self._config.llm.tool_call_max_turns,
                        "tool_call_timeout_seconds": self._config.llm.tool_call_timeout_seconds,
                    },
                    "mcp": {
                        "auto_discover": self._config.mcp.auto_discover,
                        "max_restart_attempts": self._config.mcp.max_restart_attempts,
                        "servers": self._config.mcp.servers,
                        "registries": [
                            {"name": r.name, "type": r.type, "enabled": r.enabled}
                            for r in self._config.mcp.registries
                        ],
                    },
                    "database": {
                        "host": self._config.database.host,
                        "port": self._config.database.port,
                        "name": self._config.database.name,
                    },
                }
            return {}

        @app.get("/api/safety")
        async def get_safety():
            if self._safety_config:
                return self._safety_config
            return {"blacklist": {}, "require_approval": []}

        @app.get("/api/monitoring/events")
        async def get_monitoring_events():
            return {"events": self._events[-50:]}

        @app.get("/api/monitoring/status")
        async def get_monitoring_status():
            if self._monitoring_engine:
                status = self._monitoring_engine.get_status()
                return {
                    "running": status["running"],
                    "rules": status["rules_count"],
                    "events_total": len(self._events),
                }
            return {"running": False, "rules": 0, "events_total": 0}

        @app.get("/api/usage")
        async def get_usage():
            """Return token usage and cost stats from agent."""
            if self._agent and hasattr(self._agent, 'get_usage'):
                usage = self._agent.get_usage()
                return {"usage": usage}
            return {"usage": {}}

        @app.get("/api/audit")
        async def get_audit():
            """Return recent audit log entries."""
            if self._audit_logger and hasattr(self._audit_logger, 'get_recent'):
                entries = self._audit_logger.get_recent(50)
                serialized = []
                for e in entries:
                    if hasattr(e, '__dataclass_fields__'):
                        serialized.append(asdict(e))
                    elif isinstance(e, dict):
                        serialized.append(e)
                    else:
                        serialized.append(str(e))
                return {"entries": serialized}
            return {"entries": []}

        @app.get("/api/metrics")
        async def get_metrics():
            """Return tool execution metrics."""
            if self._metrics_collector and hasattr(self._metrics_collector, 'get_summary'):
                return {"metrics": self._metrics_collector.get_summary()}
            return {"metrics": {}}

        @app.get("/api/approvals")
        async def get_approvals():
            """Return pending approval requests."""
            if self._agent and hasattr(self._agent, 'get_pending_approvals'):
                return {"approvals": self._agent.get_pending_approvals()}
            return {"approvals": []}

        @app.post("/api/approvals/{approval_id}/approve")
        async def approve_tool(approval_id: str):
            """Approve a pending tool execution."""
            if self._agent and hasattr(self._agent, 'approve_tool'):
                result = self._agent.approve_tool(approval_id)
                return {"status": "approved", "approval_id": approval_id, "result": result}
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )

        @app.post("/api/approvals/{approval_id}/deny")
        async def deny_tool(approval_id: str):
            """Deny a pending tool execution."""
            if self._agent and hasattr(self._agent, 'deny_tool'):
                result = self._agent.deny_tool(approval_id)
                return {"status": "denied", "approval_id": approval_id, "result": result}
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )

        @app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            await websocket.accept()
            async with self._lock:
                self._connections.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    user_message = msg.get("message", "")

                    if self._message_handler:
                        if asyncio.iscoroutinefunction(self._message_handler):
                            response = await self._message_handler(user_message, user="web", channel="web")
                        else:
                            response = self._message_handler(user_message, user="web", channel="web")
                    else:
                        response = "No message handler configured."

                    await websocket.send_text(json.dumps({"type": "response", "message": response}))
            except WebSocketDisconnect:
                async with self._lock:
                    if websocket in self._connections:
                        self._connections.remove(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                async with self._lock:
                    if websocket in self._connections:
                        self._connections.remove(websocket)

    async def broadcast(self, message: str):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "notification", "message": message}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)
