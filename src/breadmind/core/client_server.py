"""Client/Server Architecture Split.

OpenCode-inspired design: run LLM inference and tool execution on a
dedicated server process, control it from a lightweight client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from breadmind.utils.helpers import generate_short_id


class NodeRole(str, Enum):
    SERVER = "server"
    CLIENT = "client"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 18790
    auth_token: str = ""
    max_sessions: int = 10


@dataclass
class ClientConfig:
    server_url: str = "http://127.0.0.1:18790"
    auth_token: str = ""
    timeout: int = 300


class InferenceServer:
    """Dedicated server for LLM inference and tool execution.

    Accepts requests from lightweight clients, runs agent loop,
    streams results back.  Supports multiple concurrent sessions.
    """

    def __init__(self, config: ServerConfig | None = None) -> None:
        self._config = config or ServerConfig()
        self._sessions: dict[str, dict] = {}
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    async def start(self) -> None:
        """Start the inference server."""
        self._running = True

    async def stop(self) -> None:
        """Stop the inference server and clear sessions."""
        self._running = False
        self._sessions.clear()

    async def handle_request(self, session_id: str, prompt: str) -> dict:
        """Process an inference request.  Returns result dict."""
        if not self._running:
            raise RuntimeError("Server is not running")

        if len(self._sessions) >= self._config.max_sessions and session_id not in self._sessions:
            raise RuntimeError("Maximum sessions reached")

        self._sessions[session_id] = {"prompt": prompt, "status": "active"}

        # Simulated inference — in production would call CoreAgent
        result = {
            "session_id": session_id,
            "response": f"processed: {prompt}",
            "status": "completed",
        }
        self._sessions[session_id]["status"] = "completed"
        return result

    async def stream_response(self, session_id: str, prompt: str):
        """Stream response events for a request.

        Yields dicts representing streaming chunks.
        """
        if not self._running:
            raise RuntimeError("Server is not running")

        self._sessions[session_id] = {"prompt": prompt, "status": "streaming"}
        # Simulate streaming chunks
        for i, word in enumerate(prompt.split()):
            yield {"chunk": word, "index": i, "session_id": session_id}
        self._sessions[session_id]["status"] = "completed"


class InferenceClient:
    """Lightweight client that connects to InferenceServer.

    Can run on mobile or resource-constrained devices.
    """

    def __init__(self, config: ClientConfig | None = None) -> None:
        self._config = config or ClientConfig()
        self._connected = False
        self._session_id = generate_short_id(12)

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to the inference server."""
        if not self._config.server_url:
            raise ValueError("Server URL is required")
        self._connected = True
        return True

    async def send_prompt(self, prompt: str, session_id: str = "") -> dict:
        """Send a prompt to the server and get the response."""
        if not self._connected:
            raise RuntimeError("Not connected — call connect() first")

        sid = session_id or self._session_id
        # Simulated — in production would make HTTP request
        return {
            "session_id": sid,
            "response": f"client-processed: {prompt}",
            "status": "completed",
        }

    async def stream_prompt(self, prompt: str, session_id: str = ""):
        """Stream response from the server."""
        if not self._connected:
            raise RuntimeError("Not connected — call connect() first")

        sid = session_id or self._session_id
        for i, word in enumerate(prompt.split()):
            yield {"chunk": word, "index": i, "session_id": sid}

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
