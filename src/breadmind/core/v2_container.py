"""v2 DI 컨테이너. 프로토콜 → 구현체 매핑."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Container:
    """DI 컨테이너."""

    def __init__(self) -> None:
        self._instances: dict[type, Any] = {}
        self._factories: dict[type, Callable[[Container], Any]] = {}

    def register(self, protocol: type[T], instance: T) -> None:
        self._instances[protocol] = instance

    def register_factory(self, protocol: type[T], factory: Callable[[Container], T]) -> None:
        self._factories[protocol] = factory

    def resolve(self, protocol: type[T]) -> T:
        if protocol in self._instances:
            return self._instances[protocol]
        if protocol in self._factories:
            instance = self._factories[protocol](self)
            self._instances[protocol] = instance
            return instance
        raise KeyError(f"No registration found for {protocol}")

    def has(self, protocol: type) -> bool:
        return protocol in self._instances or protocol in self._factories
