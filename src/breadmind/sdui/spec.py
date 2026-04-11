"""UISpec dataclasses for Server-Driven UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Component:
    type: str
    id: str
    props: dict[str, Any] = field(default_factory=dict)
    children: list["Component"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "props": self.props,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Component":
        return cls(
            type=data["type"],
            id=data["id"],
            props=data.get("props", {}),
            children=[cls.from_dict(c) for c in data.get("children", [])],
        )


@dataclass
class UISpec:
    schema_version: int
    root: Component
    bindings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root.to_dict(),
            "bindings": self.bindings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UISpec":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            root=Component.from_dict(data["root"]),
            bindings=data.get("bindings", {}),
        )
