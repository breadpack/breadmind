"""Serialization mixin for dataclasses."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


def _default_serializer(obj: Any) -> Any:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class SerializableMixin:
    """Mixin that adds to_dict/from_dict/to_json/from_json to dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dict with proper type handling."""
        return json.loads(json.dumps(dataclasses.asdict(self), default=_default_serializer))

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Create instance from dict, ignoring unknown fields."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls: type[T], json_str: str) -> T:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
