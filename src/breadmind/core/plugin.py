"""v2 플러그인 로더: 발견, 로드, 의존성 해석."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from breadmind.core.container import Container
from breadmind.core.events import EventBus


@dataclass
class PluginManifest:
    """플러그인 메타데이터."""
    name: str
    version: str
    provides: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


class PluginLoader:
    """플러그인 발견, 로드, 의존성 해석."""

    def __init__(self, container: Container, events: EventBus) -> None:
        self._container = container
        self._events = events
        self._plugins: dict[str, Any] = {}

    def register(self, plugin: Any) -> None:
        name = plugin.manifest.name
        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' already registered")
        self._plugins[name] = plugin

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    async def setup_all(self) -> None:
        ordered = self._resolve_order()
        for name in ordered:
            plugin = self._plugins[name]
            await plugin.setup(self._container, self._events)

    async def teardown_all(self) -> None:
        for plugin in reversed(list(self._plugins.values())):
            await plugin.teardown()

    def _resolve_order(self) -> list[str]:
        """토폴로지 정렬로 의존성 순서 결정."""
        visited: set[str] = set()
        order: list[str] = []
        provides_map: dict[str, str] = {}

        for name, plugin in self._plugins.items():
            for p in plugin.manifest.provides:
                provides_map[p] = name

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            plugin = self._plugins.get(name)
            if plugin:
                for dep in plugin.manifest.depends_on:
                    provider_name = provides_map.get(dep, dep)
                    if provider_name in self._plugins:
                        visit(provider_name)
            order.append(name)

        for name in self._plugins:
            visit(name)

        return order
