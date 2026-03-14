import asyncio
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Callable, Any

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, message_handler: Callable | None = None, tool_registry=None, mcp_manager=None):
        self.app = FastAPI(title="BreadMind", version="0.1.0")
        self._message_handler = message_handler
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._connections: list[WebSocket] = []
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.get("/health")
        async def health():
            return {"status": "ok", "version": "0.1.0"}

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

        @app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            await websocket.accept()
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
                self._connections.remove(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if websocket in self._connections:
                    self._connections.remove(websocket)

    async def broadcast(self, message: str):
        for ws in self._connections[:]:
            try:
                await ws.send_text(json.dumps({"type": "notification", "message": message}))
            except Exception:
                self._connections.remove(ws)
