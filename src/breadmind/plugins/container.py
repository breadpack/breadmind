"""Service container for dependency injection into plugins."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ServiceContainer:
    """Holds all shared application services. Injected into plugins at load time."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, key: str, instance: Any) -> None:
        self._services[key] = instance

    def get(self, key: str) -> Any:
        if key not in self._services:
            raise KeyError(f"Service not registered: {key}")
        return self._services[key]

    def has(self, key: str) -> bool:
        return key in self._services

    def get_optional(self, key: str, default: Any = None) -> Any:
        return self._services.get(key, default)

    def keys(self) -> list[str]:
        return list(self._services.keys())
