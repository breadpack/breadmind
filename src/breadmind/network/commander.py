"""Commander: WebSocket hub, LLM proxy, task dispatch."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from breadmind.network.protocol import (
    MessageEnvelope, MessageType, SequenceTracker,
    create_message, serialize_message,
)
from breadmind.network.registry import (
    AgentRegistry, AgentStatus, RoleDefinition,
)

try:
    from breadmind.llm.base import LLMMessage, ToolDefinition
except ImportError:
    LLMMessage = None
    ToolDefinition = None

logger = logging.getLogger(__name__)


class Commander:
    """Central hub managing worker agents."""

    def __init__(
        self,
        registry: AgentRegistry,
        llm_provider: Any,
        session_key: bytes,
        on_task_result: Callable | None = None,
    ) -> None:
        self._registry = registry
        self._llm_provider = llm_provider
        self._session_key = session_key
        self._on_task_result = on_task_result
        self._connections: dict[str, Any] = {}  # agent_id -> websocket
        self._seq_trackers: dict[str, SequenceTracker] = {}
        self.completed_tasks: dict[str, dict] = {}

    def add_connection(self, agent_id: str, ws: Any) -> None:
        self._connections[agent_id] = ws
        self._seq_trackers[agent_id] = SequenceTracker()

    def remove_connection(self, agent_id: str) -> None:
        self._connections.pop(agent_id, None)
        self._seq_trackers.pop(agent_id, None)

    async def handle_message(
        self, msg: MessageEnvelope, ws: Any, agent_id: str,
    ) -> None:
        """Route incoming message from a worker."""
        if msg.type == MessageType.HEARTBEAT:
            await self._handle_heartbeat(msg, ws, agent_id)
        elif msg.type == MessageType.TASK_RESULT:
            await self._handle_task_result(msg, agent_id)
        elif msg.type == MessageType.LLM_REQUEST:
            await self._handle_llm_request(msg, ws, agent_id)
        elif msg.type == MessageType.SYNC:
            await self._handle_sync(msg, agent_id)
        else:
            logger.warning("Unknown message type from %s: %s", agent_id, msg.type)

    async def dispatch_task(
        self,
        agent_id: str,
        task_type: str,
        params: dict,
        trace_id: str | None = None,
    ) -> str:
        """Send a task to a worker. Returns task_id."""
        task_id = str(uuid.uuid4())
        idempotency_key = str(uuid.uuid4())
        msg = create_message(
            type=MessageType.TASK_ASSIGN,
            source="commander",
            target=agent_id,
            payload={
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "type": task_type,
                "params": params,
            },
            trace_id=trace_id,
        )
        await self._send(agent_id, msg)
        return task_id

    async def send_role_update(self, agent_id: str, role: RoleDefinition) -> None:
        msg = create_message(
            type=MessageType.ROLE_UPDATE,
            source="commander",
            target=agent_id,
            payload={"role": role.to_dict()},
        )
        self._registry.assign_role(agent_id, role)
        await self._send(agent_id, msg)

    async def send_command(
        self, agent_id: str, action: str, params: dict | None = None,
    ) -> None:
        msg = create_message(
            type=MessageType.COMMAND,
            source="commander",
            target=agent_id,
            payload={"action": action, **(params or {})},
        )
        await self._send(agent_id, msg)

    # --- Private handlers ---

    async def _handle_heartbeat(
        self, msg: MessageEnvelope, ws: Any, agent_id: str,
    ) -> None:
        payload = msg.payload
        agent = self._registry.get(agent_id)
        if agent is None:
            self._registry.register(
                agent_id=agent_id,
                host=payload.get("host", "unknown"),
                environment=payload.get("environment", {}),
            )
            self.add_connection(agent_id, ws)
        self._registry.update_heartbeat(agent_id, {
            k: v for k, v in payload.items() if k not in ("environment", "host")
        })

    async def _handle_task_result(
        self, msg: MessageEnvelope, agent_id: str,
    ) -> None:
        payload = msg.payload
        task_id = payload.get("task_id")
        self.completed_tasks[task_id] = payload
        logger.info(
            "Task %s completed by %s: %s",
            task_id, agent_id, payload.get("status"),
        )
        if self._on_task_result:
            await self._on_task_result(agent_id, payload)

    async def _handle_llm_request(
        self, msg: MessageEnvelope, ws: Any, agent_id: str,
    ) -> None:
        payload = msg.payload
        try:
            response = await self._llm_provider.chat(
                messages=payload.get("messages", []),
                tools=payload.get("tools") or None,
            )
            tool_calls = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_calls = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ]
            reply = create_message(
                type=MessageType.LLM_RESPONSE,
                source="commander",
                target=agent_id,
                payload={
                    "content": response.content,
                    "tool_calls": tool_calls,
                    "stop_reason": response.stop_reason,
                },
                reply_to=msg.id,
                trace_id=msg.trace_id,
            )
        except Exception as e:
            logger.exception("LLM proxy error for %s", agent_id)
            reply = create_message(
                type=MessageType.LLM_RESPONSE,
                source="commander",
                target=agent_id,
                payload={"error": str(e)},
                reply_to=msg.id,
            )
        await self._send_raw(ws, reply)

    async def _handle_sync(
        self, msg: MessageEnvelope, agent_id: str,
    ) -> None:
        results = msg.payload.get("results", [])
        for result in results:
            task_id = result.get("task_id")
            if task_id not in self.completed_tasks:
                self.completed_tasks[task_id] = result
        logger.info("Synced %d results from %s", len(results), agent_id)
        self._registry.set_status(agent_id, AgentStatus.ACTIVE)

    # --- Send helpers ---

    async def _send(self, agent_id: str, msg: MessageEnvelope) -> None:
        ws = self._connections.get(agent_id)
        if ws:
            await self._send_raw(ws, msg)
        else:
            logger.warning("No connection for agent %s", agent_id)

    async def _send_raw(self, ws: Any, msg: MessageEnvelope) -> None:
        raw = serialize_message(msg, self._session_key)
        await ws.send(raw)
