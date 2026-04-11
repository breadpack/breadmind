"""Agent registry: tracks worker agents, status, roles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    REGISTERING = "registering"
    IDLE = "idle"
    ACTIVE = "active"
    OFFLINE = "offline"
    SYNCING = "syncing"
    DRAINING = "draining"
    REMOVED = "removed"


@dataclass
class RoleDefinition:
    name: str
    tools: list[str]
    schedules: list[dict]
    policies: dict[str, list[str]]
    reactive_triggers: list[dict] = field(default_factory=list)
    escalation: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tools": self.tools,
            "schedules": self.schedules,
            "policies": self.policies,
            "reactive_triggers": self.reactive_triggers,
            "escalation": self.escalation,
            "limits": self.limits,
        }


@dataclass
class AgentInfo:
    agent_id: str
    host: str
    status: AgentStatus = AgentStatus.REGISTERING
    environment: dict[str, Any] = field(default_factory=dict)
    roles: list[RoleDefinition] = field(default_factory=list)
    cert_fingerprint: str | None = None
    last_heartbeat: datetime | None = None
    last_metrics: dict[str, Any] = field(default_factory=dict)
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRegistry:
    """In-memory registry of connected worker agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}

    def register(
        self,
        agent_id: str,
        host: str,
        environment: dict | None = None,
        cert_fingerprint: str | None = None,
    ) -> AgentInfo:
        info = AgentInfo(
            agent_id=agent_id,
            host=host,
            environment=environment or {},
            cert_fingerprint=cert_fingerprint,
        )
        self._agents[agent_id] = info
        logger.info("Agent registered: %s @ %s", agent_id, host)
        return info

    def get(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.status = status

    def update_heartbeat(self, agent_id: str, metrics: dict) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc)
            agent.last_metrics = metrics

    def assign_role(self, agent_id: str, role: RoleDefinition) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            # Remove existing role with same name if any
            agent.roles = [r for r in agent.roles if r.name != role.name]
            agent.roles.append(role)

    def remove_role(self, agent_id: str, role_name: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.roles = [r for r in agent.roles if r.name != role_name]

    def list_by_status(self, status: AgentStatus) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.status == status]

    def list_all(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def detect_offline(self, threshold_seconds: int = 90) -> list[str]:
        """Find agents whose last heartbeat exceeds threshold."""
        now = datetime.now(timezone.utc)
        offline = []
        for agent_id, info in self._agents.items():
            if info.status in (AgentStatus.ACTIVE, AgentStatus.IDLE):
                if info.last_heartbeat is None:
                    continue
                delta = (now - info.last_heartbeat).total_seconds()
                if delta > threshold_seconds:
                    offline.append(agent_id)
        return offline

    def list_companions(self) -> list[AgentInfo]:
        """Return agents whose environment.agent_type == 'companion'."""
        return [
            a for a in self._agents.values()
            if a.environment.get("agent_type") == "companion"
        ]

    def list_workers(self) -> list[AgentInfo]:
        """Return agents that are NOT companions (traditional workers)."""
        return [
            a for a in self._agents.values()
            if a.environment.get("agent_type") != "companion"
        ]

    def remove(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
