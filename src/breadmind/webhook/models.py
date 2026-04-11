"""Data models for the webhook automation pipeline system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Types of actions that can be performed in a pipeline."""

    SEND_TO_AGENT = "send_to_agent"
    CALL_TOOL = "call_tool"
    HTTP_REQUEST = "http_request"
    NOTIFY = "notify"
    TRANSFORM = "transform"


class FailureStrategy(str, Enum):
    """Strategy to apply when a pipeline action fails."""

    STOP = "stop"
    CONTINUE = "continue"
    RETRY = "retry"
    FALLBACK = "fallback"


class PermissionLevel(str, Enum):
    """Permission levels that control which action types are allowed."""

    READ_ONLY = "read_only"
    STANDARD = "standard"
    ELEVATED = "elevated"
    ADMIN = "admin"

    def can_execute(self, action_type: ActionType) -> bool:
        """Return True if this permission level allows the given action type."""
        _allowed: dict[PermissionLevel, set[ActionType]] = {
            PermissionLevel.READ_ONLY: {
                ActionType.TRANSFORM,
                ActionType.NOTIFY,
            },
            PermissionLevel.STANDARD: {
                ActionType.TRANSFORM,
                ActionType.NOTIFY,
                ActionType.SEND_TO_AGENT,
                ActionType.HTTP_REQUEST,
            },
            PermissionLevel.ELEVATED: {
                ActionType.TRANSFORM,
                ActionType.NOTIFY,
                ActionType.SEND_TO_AGENT,
                ActionType.HTTP_REQUEST,
                ActionType.CALL_TOOL,
            },
            PermissionLevel.ADMIN: set(ActionType),
        }
        return action_type in _allowed.get(self, set())


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class PipelineAction:
    """A single action within a pipeline."""

    action_type: ActionType
    config: dict[str, Any] = field(default_factory=dict)
    on_failure: FailureStrategy = FailureStrategy.STOP
    max_retries: int = 0
    fallback_action_id: str | None = None
    capture_response: bool = False
    response_variable: str = ""
    timeout: int = 30
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type.value,
            "config": self.config,
            "on_failure": self.on_failure.value,
            "max_retries": self.max_retries,
            "fallback_action_id": self.fallback_action_id,
            "capture_response": self.capture_response,
            "response_variable": self.response_variable,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineAction:
        return cls(
            id=data.get("id", _new_id()),
            action_type=ActionType(data["action_type"]),
            config=data.get("config", {}),
            on_failure=FailureStrategy(data.get("on_failure", FailureStrategy.STOP.value)),
            max_retries=data.get("max_retries", 0),
            fallback_action_id=data.get("fallback_action_id"),
            capture_response=data.get("capture_response", False),
            response_variable=data.get("response_variable", ""),
            timeout=data.get("timeout", 30),
        )


@dataclass
class Pipeline:
    """An ordered sequence of actions triggered by a webhook rule."""

    name: str
    actions: list[PipelineAction] = field(default_factory=list)
    description: str = ""
    enabled: bool = True
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "actions": [a.to_dict() for a in self.actions],
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pipeline:
        return cls(
            id=data.get("id", _new_id()),
            name=data["name"],
            description=data.get("description", ""),
            actions=[PipelineAction.from_dict(a) for a in data.get("actions", [])],
            enabled=data.get("enabled", True),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(timezone.utc),
        )


@dataclass
class WebhookRule:
    """A rule that maps an incoming webhook event to a pipeline."""

    name: str
    endpoint_id: str
    condition: str
    priority: int
    pipeline_id: str
    enabled: bool = True
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "endpoint_id": self.endpoint_id,
            "condition": self.condition,
            "priority": self.priority,
            "pipeline_id": self.pipeline_id,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookRule:
        return cls(
            id=data.get("id", _new_id()),
            name=data["name"],
            endpoint_id=data["endpoint_id"],
            condition=data["condition"],
            priority=data["priority"],
            pipeline_id=data["pipeline_id"],
            enabled=data.get("enabled", True),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(timezone.utc),
        )


@dataclass
class PipelineContext:
    """Runtime context passed through pipeline action execution."""

    payload: dict[str, Any]
    headers: dict[str, str]
    endpoint: str
    steps: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
