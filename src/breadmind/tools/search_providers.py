"""Multiple search backends with unified interface for BreadMind."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SearchProvider(str, Enum):
    DEFAULT = "default"       # Built-in basic search


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    date: str = ""
    source: str = ""
    metadata: dict = field(default_factory=dict)


class SearchBackend(ABC):
    """Abstract search backend."""

    @abstractmethod
    async def search(
        self, query: str, limit: int = 10, **kwargs
    ) -> list[SearchResult]:
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if required API keys/config are present."""
        ...


class SearchProviderManager:
    """Manages multiple search backends with fallback."""

    def __init__(self) -> None:
        self._backends: dict[SearchProvider, SearchBackend] = {}
        self._default: SearchProvider = SearchProvider.DEFAULT

    def set_default(self, provider: SearchProvider) -> None:
        """Set the default search provider."""
        self._default = provider

    async def search(
        self,
        query: str,
        provider: SearchProvider | None = None,
        limit: int = 10,
        **kwargs,
    ) -> list[SearchResult]:
        """Search using specified or default provider. Falls back if unavailable."""
        target = provider or self._default

        # Try the requested provider first
        if target in self._backends:
            backend = self._backends[target]
            if backend.is_configured():
                return await backend.search(query, limit=limit, **kwargs)

        # Fallback: try all configured providers in order
        for p, backend in self._backends.items():
            if p == target:
                continue
            if backend.is_configured():
                logger.info(
                    "Falling back from %s to %s", target.value, p.value
                )
                return await backend.search(query, limit=limit, **kwargs)

        raise ValueError(
            "No search provider is configured. "
            "Register a search backend via manager.register()."
        )

    def available_providers(self) -> list[SearchProvider]:
        """Return list of configured (available) providers."""
        return [p for p, b in self._backends.items() if b.is_configured()]

    def register(self, name: SearchProvider, backend: SearchBackend) -> None:
        """Register a custom search backend."""
        self._backends[name] = backend
