"""Data models for the webhook automation pipeline system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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
    capture_response: bool = False
    response_variable: str = ""
    timeout: int = 30
    max_retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "config": self.config,
            "on_failure": self.on_failure.value,
            "capture_response": self.capture_response,
            "response_variable": self.response_variable,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineAction:
        return cls(
            action_type=ActionType(data["action_type"]),
            config=data.get("config", {}),
            on_failure=FailureStrategy(data.get("on_failure", FailureStrategy.STOP.value)),
            capture_response=data.get("capture_response", False),
            response_variable=data.get("response_variable", ""),
            timeout=data.get("timeout", 30),
            max_retries=data.get("max_retries", 0),
        )


@dataclass
class Pipeline:
    """An ordered sequence of actions triggered by a webhook rule."""

    name: str
    actions: list[PipelineAction] = field(default_factory=list)
    id: str = field(default_factory=_new_id)
    enabled: bool = True
    description: str = ""
    permission_level: PermissionLevel = PermissionLevel.STANDARD

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "permission_level": self.permission_level.value,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pipeline:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            permission_level=PermissionLevel(
                data.get("permission_level", PermissionLevel.STANDARD.value)
            ),
            actions=[PipelineAction.from_dict(a) for a in data.get("actions", [])],
        )


@dataclass
class WebhookRule:
    """A rule that maps an incoming webhook event to a pipeline."""

    name: str
    endpoint_id: str
    condition: str
    priority: int
    pipeline_id: str
    id: str = field(default_factory=_new_id)
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "endpoint_id": self.endpoint_id,
            "condition": self.condition,
            "priority": self.priority,
            "pipeline_id": self.pipeline_id,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookRule:
        return cls(
            id=data["id"],
            name=data["name"],
            endpoint_id=data["endpoint_id"],
            condition=data["condition"],
            priority=data["priority"],
            pipeline_id=data["pipeline_id"],
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
        )


@dataclass
class PipelineContext:
    """Runtime context passed through pipeline action execution."""

    payload: dict[str, Any]
    headers: dict[str, str]
    endpoint: str
    steps: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
