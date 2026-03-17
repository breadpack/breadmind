"""Service adapter interfaces and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SyncResult:
    created: list[str]
    updated: list[str]
    deleted: list[str]
    errors: list[str]
    synced_at: datetime = field(default_factory=_utcnow)


class ServiceAdapter(ABC):
    @property
    @abstractmethod
    def domain(self) -> str: ...
    @property
    @abstractmethod
    def source(self) -> str: ...
    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool: ...
    @abstractmethod
    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list: ...
    @abstractmethod
    async def get_item(self, source_id: str) -> Any: ...
    @abstractmethod
    async def create_item(self, entity: Any) -> str: ...
    @abstractmethod
    async def update_item(self, source_id: str, changes: dict) -> bool: ...
    @abstractmethod
    async def delete_item(self, source_id: str) -> bool: ...
    @abstractmethod
    async def sync(self, since: datetime | None = None) -> SyncResult: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], ServiceAdapter] = {}

    def register(self, adapter: ServiceAdapter) -> None:
        key = (adapter.domain, adapter.source)
        self._adapters[key] = adapter

    def get_adapter(self, domain: str, source: str) -> ServiceAdapter:
        key = (domain, source)
        if key not in self._adapters:
            raise KeyError(f"No adapter registered for ({domain}, {source})")
        return self._adapters[key]

    def list_adapters(self, domain: str | None = None) -> list[ServiceAdapter]:
        if domain is None:
            return list(self._adapters.values())
        return [a for (d, _), a in self._adapters.items() if d == domain]

    async def sync_all(self, domain: str | None = None) -> dict[str, SyncResult]:
        results: dict[str, SyncResult] = {}
        for adapter in self.list_adapters(domain):
            key = f"{adapter.domain}:{adapter.source}"
            results[key] = await adapter.sync()
        return results
