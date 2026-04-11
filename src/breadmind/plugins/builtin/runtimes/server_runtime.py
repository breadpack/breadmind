"""v2 서버 런타임: FastAPI + WebSocket."""
from __future__ import annotations

import json
import logging
from typing import Any

from breadmind.constants import DEFAULT_WEB_PORT
from breadmind.core.protocols import UserInput, AgentOutput, Progress

logger = logging.getLogger("breadmind.server_runtime")


class ServerRuntime:
    """FastAPI 서버 런타임. RuntimeProtocol 구현."""

    def __init__(self, agent: Any, host: str = "0.0.0.0", port: int = DEFAULT_WEB_PORT) -> None:
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
                    stream = msg.get("stream", False)
                    try:
                        if stream:
                            await self._handle_ws_stream(websocket, message, user)
                        else:
                            response = await self._agent.run(
                                message, user=user, channel="websocket",
                            )
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

    async def _handle_ws_stream(self, websocket: Any, message: str, user: str) -> None:
        """WebSocket 스트리밍: StreamEvent를 JSON으로 직렬화하여 전송."""
        from breadmind.core.protocols import AgentContext
        from breadmind.plugins.builtin.agent_loop.message_loop import (
            MessageLoopAgent,
        )

        # Agent 빌드 (SDK Agent의 내부 MessageLoopAgent에 접근)
        agent = self._agent
        agent._build()

        provider = agent.plugins.get("provider")
        prompt_builder = agent.plugins.get("prompt_builder")
        tool_registry = agent.plugins.get("tool_registry")

        if provider is None:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": "Provider not configured",
            }))
            return

        if prompt_builder is None:
            from breadmind.core.protocols import PromptBlock

            class MinimalPromptBuilder:
                def build(self, ctx):
                    return [PromptBlock(
                        section="identity",
                        content=f"You are {ctx.persona_name}.",
                        cacheable=True, priority=1,
                    )]
            prompt_builder = MinimalPromptBuilder()

        if tool_registry is None:
            from breadmind.plugins.builtin.tools.registry import HybridToolRegistry
            tool_registry = HybridToolRegistry()

        loop_agent = MessageLoopAgent(
            provider=provider,
            prompt_builder=prompt_builder,
            tool_registry=tool_registry,
            safety_guard=agent._safety,
            max_turns=agent.config.max_turns,
            prompt_context=agent._prompt_context,
        )

        ctx = AgentContext(
            user=user, channel="websocket",
            session_id=f"{user}:websocket",
        )

        async for event in loop_agent.handle_message_stream(message, ctx):
            await websocket.send_text(json.dumps({
                "type": event.type,
                "data": event.data,
            }))

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
