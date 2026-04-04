"""v2 서버 런타임: FastAPI + WebSocket."""
from __future__ import annotations

import json
import logging
from typing import Any

from breadmind.core.protocols import UserInput, AgentOutput, Progress

logger = logging.getLogger("breadmind.server_runtime")


class ServerRuntime:
    """FastAPI 서버 런타임. RuntimeProtocol 구현."""

    def __init__(self, agent: Any, host: str = "0.0.0.0", port: int = 8080) -> None:
        self._agent = agent
        self._host = host
        self._port = port
        self._app: Any = None

    def create_app(self) -> Any:
        """FastAPI 앱 생성."""
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import JSONResponse

        app = FastAPI(title=f"BreadMind v2 - {self._agent.name}")

        @app.get("/health")
        async def health():
            return JSONResponse({"status": "ok", "agent": self._agent.name})

        @app.post("/api/chat")
        async def chat(request: dict):
            message = request.get("message", "")
            user = request.get("user", "api_user")
            try:
                response = await self._agent.run(message, user=user, channel="api")
                return JSONResponse({"response": response})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.websocket("/ws/chat")
        async def ws_chat(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    message = msg.get("message", "")
                    user = msg.get("user", "ws_user")
                    try:
                        response = await self._agent.run(message, user=user, channel="websocket")
                        await websocket.send_text(json.dumps({
                            "type": "response",
                            "message": response,
                        }))
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": str(e),
                        }))
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")

        self._app = app
        return app

    async def start(self, container: Any) -> None:
        import uvicorn
        app = self.create_app()
        config = uvicorn.Config(app, host=self._host, port=self._port)
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self) -> None:
        pass

    async def receive(self) -> UserInput:
        raise NotImplementedError("Server runtime uses HTTP/WS, not polling")

    async def send(self, output: AgentOutput) -> None:
        raise NotImplementedError("Server runtime uses HTTP/WS, not push")

    async def send_progress(self, progress: Progress) -> None:
        pass
