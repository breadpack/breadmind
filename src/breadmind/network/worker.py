"""Worker agent runtime: executes tasks locally, reports to Commander."""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from breadmind.network.protocol import (
    MessageEnvelope, MessageType, SequenceTracker,
    create_message, serialize_message, deserialize_message,
)

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    STARTING = "starting"
    REGISTERING = "registering"
    IDLE = "idle"
    ACTIVE = "active"
    OFFLINE = "offline"
    SYNCING = "syncing"
    DRAINING = "draining"


class Worker:
    """Lightweight agent that executes tasks locally."""

    def __init__(
        self,
        agent_id: str,
        commander_url: str,
        session_key: bytes,
        tool_registry: Any,
    ) -> None:
        self.agent_id = agent_id
        self._commander_url = commander_url
        self._session_key = session_key
        self._tools = tool_registry
        self._ws: Any | None = None
        self._seq = SequenceTracker()
        self.state = WorkerState.STARTING
        self.roles: dict[str, dict] = {}
        self._offline_queue: list[dict] = []
        self._task_history: dict[str, dict] = {}

    async def handle_message(self, msg: MessageEnvelope) -> None:
        """Route incoming message from Commander."""
        if msg.type == MessageType.TASK_ASSIGN:
            await self._handle_task_assign(msg)
        elif msg.type == MessageType.ROLE_UPDATE:
            await self._handle_role_update(msg)
        elif msg.type == MessageType.COMMAND:
            await self._handle_command(msg)
        elif msg.type == MessageType.LLM_RESPONSE:
            await self._handle_llm_response(msg)
        else:
            logger.warning("Unknown message type: %s", msg.type)

    async def send_heartbeat(self) -> None:
        """Send heartbeat with system metrics to Commander."""
        try:
            import psutil
            payload = {
                "cpu": psutil.cpu_percent() / 100,
                "memory": psutil.virtual_memory().percent / 100,
                "disk": psutil.disk_usage("/").percent / 100,
                "queue_size": len(self._offline_queue),
            }
        except ImportError:
            payload = {"queue_size": len(self._offline_queue)}
        msg = create_message(
            type=MessageType.HEARTBEAT,
            source=self.agent_id,
            target="commander",
            payload=payload,
        )
        await self._send(msg)

    async def sync_offline_queue(self) -> None:
        """Send queued results to Commander."""
        if not self._offline_queue:
            return
        msg = create_message(
            type=MessageType.SYNC,
            source=self.agent_id,
            target="commander",
            payload={"results": list(self._offline_queue)},
        )
        await self._send(msg)
        self._offline_queue.clear()
        self.state = WorkerState.ACTIVE

    # --- Private handlers ---

    async def _handle_task_assign(self, msg: MessageEnvelope) -> None:
        payload = msg.payload
        task_id = payload["task_id"]
        tool_name = payload.get("params", {}).get("tool", "")
        arguments = payload.get("params", {}).get("arguments", {})

        # Check if tool is blocked by any role policy
        if self._is_tool_blocked(tool_name):
            result = {
                "task_id": task_id,
                "status": "failure",
                "output": f"Tool '{tool_name}' is blocked by role policy",
                "metrics": {},
            }
        else:
            start = time.monotonic()
            try:
                tool_result = await self._tools.execute(tool_name, arguments)
                result = {
                    "task_id": task_id,
                    "status": "success" if tool_result.success else "failure",
                    "output": tool_result.output,
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }
            except Exception as e:
                result = {
                    "task_id": task_id,
                    "status": "failure",
                    "output": str(e),
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }

        self._task_history[task_id] = result

        if self._ws is not None:
            reply = create_message(
                type=MessageType.TASK_RESULT,
                source=self.agent_id,
                target="commander",
                payload=result,
                reply_to=msg.id,
                trace_id=msg.trace_id,
            )
            await self._send(reply)
        else:
            self._offline_queue.append(result)

    async def _handle_role_update(self, msg: MessageEnvelope) -> None:
        role_data = msg.payload.get("role", {})
        name = role_data.get("name")
        if name:
            self.roles[name] = role_data
            logger.info("Role updated: %s", name)

    async def _handle_command(self, msg: MessageEnvelope) -> None:
        action = msg.payload.get("action")
        if action == "restart":
            await self._restart()
        elif action == "decommission":
            self.state = WorkerState.DRAINING
        else:
            logger.warning("Unknown command action: %s", action)

    async def _handle_llm_response(self, msg: MessageEnvelope) -> None:
        # Will be used by tasks that need LLM reasoning
        # For now, store for pending LLM requests
        pass

    async def _restart(self) -> None:
        logger.info("Worker restart requested")
        # Actual restart logic will be implemented with process management

    def _is_tool_blocked(self, tool_name: str) -> bool:
        for role in self.roles.values():
            policies = role.get("policies", {})
            blocked = policies.get("blocked", [])
            if tool_name in blocked:
                return True
        return False

    async def _send(self, msg: MessageEnvelope) -> None:
        if self._ws is not None:
            raw = serialize_message(msg, self._session_key)
            await self._ws.send(raw)
