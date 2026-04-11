"""Browser macro data models — recording and replay of browser action sequences."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MacroStep:
    """A single recorded browser action."""

    tool: str       # Tool name: "browser_navigate", "browser_action", etc.
    params: dict    # Tool call parameters

    def to_dict(self) -> dict:
        return {"tool": self.tool, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: dict) -> MacroStep:
        return cls(tool=data["tool"], params=data.get("params", {}))


@dataclass
class BrowserMacro:
    """A named sequence of browser actions."""

    id: str
    name: str
    steps: list[MacroStep]
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_count: int = 0
    last_executed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "execution_count": self.execution_count,
            "last_executed_at": self.last_executed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BrowserMacro:
        steps = [MacroStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            steps=steps,
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            execution_count=data.get("execution_count", 0),
            last_executed_at=data.get("last_executed_at", ""),
        )
