"""FlowEvent dataclass and enums for the Durable Task Flow system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID


class EventType(str, Enum):
    FLOW_CREATED = "flow_created"
    DAG_PROPOSED = "dag_proposed"
    DAG_MUTATED = "dag_mutated"
    DAG_MUTATION_REJECTED = "dag_mutation_rejected"
    STEP_QUEUED = "step_queued"
    STEP_STARTED = "step_started"
    STEP_PROGRESS = "step_progress"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    ESCALATION_RAISED = "escalation_raised"
    USER_INTERVENTION = "user_intervention"
    FLOW_PAUSED = "flow_paused"
    FLOW_RESUMED = "flow_resumed"
    FLOW_CANCELLED = "flow_cancelled"
    FLOW_COMPLETED = "flow_completed"
    FLOW_FAILED = "flow_failed"


class FlowActor(str, Enum):
    AGENT = "agent"
    WORKER = "worker"
    USER = "user"
    SCHEDULER = "scheduler"
    RECOVERY = "recovery"
    ENGINE = "engine"


@dataclass
class FlowEvent:
    flow_id: UUID
    seq: int
    event_type: EventType
    payload: dict[str, Any]
    actor: FlowActor
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": str(self.flow_id),
            "seq": self.seq,
            "event_type": self.event_type.value,
            "payload": self.payload,
            "actor": self.actor.value,
            "created_at": self.created_at.isoformat(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowEvent:
        return cls(
            flow_id=UUID(data["flow_id"]),
            seq=int(data["seq"]),
            event_type=EventType(data["event_type"]),
            payload=data.get("payload", {}),
            actor=FlowActor(data["actor"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            schema_version=int(data.get("schema_version", 1)),
        )
