"""Multiple search backends with unified interface for BreadMind.

Supports Exa, Tavily, Firecrawl, and SearXNG with automatic fallback.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SearchProvider(str, Enum):
    DEFAULT = "default"       # Built-in basic search
    EXA = "exa"               # Exa search with date filters
    TAVILY = "tavily"         # Tavily with LLM-optimized results
    FIRECRAWL = "firecrawl"   # Firecrawl with URL scraping
    SEARXNG = "searxng"       # Self-hosted SearXNG


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


class ExaSearch(SearchBackend):
    """Exa search with native date filters and search modes."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("EXA_API_KEY", "")

    async def search(
        self, query: str, limit: int = 10, **kwargs
    ) -> list[SearchResult]:
        if not self.is_configured():
            raise ValueError("Exa API key not configured")

        # Production implementation would call Exa API via aiohttp
        # For now, raise NotImplementedError to signal real HTTP needed
        raise NotImplementedError(
            "Exa search requires aiohttp call to api.exa.ai/search"
        )

    def is_configured(self) -> bool:
        return bool(self._api_key)


class TavilySearch(SearchBackend):
    """Tavily search optimized for LLM consumption."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    async def search(
        self, query: str, limit: int = 10, **kwargs
    ) -> list[SearchResult]:
        if not self.is_configured():
            raise ValueError("Tavily API key not configured")

        raise NotImplementedError(
            "Tavily search requires aiohttp call to api.tavily.com/search"
        )

    async def extract(self, urls: list[str]) -> list[dict]:
        """Extract content from URLs (Tavily-specific feature)."""
        if not self.is_configured():
            raise ValueError("Tavily API key not configured")

        raise NotImplementedError(
            "Tavily extract requires aiohttp call to api.tavily.com/extract"
        )

    def is_configured(self) -> bool:
        return bool(self._api_key)


class FirecrawlSearch(SearchBackend):
    """Firecrawl search with URL-to-markdown conversion."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")

    async def search(
        self, query: str, limit: int = 10, **kwargs
    ) -> list[SearchResult]:
        if not self.is_configured():
            raise ValueError("Firecrawl API key not configured")

        raise NotImplementedError(
            "Firecrawl search requires aiohttp call to api.firecrawl.dev/v1/search"
        )

    async def scrape(self, url: str) -> str:
        """Scrape URL and convert to LLM-ready markdown."""
        if not self.is_configured():
            raise ValueError("Firecrawl API key not configured")

        raise NotImplementedError(
            "Firecrawl scrape requires aiohttp call to api.firecrawl.dev/v1/scrape"
        )

    def is_configured(self) -> bool:
        return bool(self._api_key)


class SearXNGSearch(SearchBackend):
    """Self-hosted SearXNG instance."""

    def __init__(self, host: str | None = None):
        self._host = host or os.environ.get("SEARXNG_HOST", "")

    async def search(
        self, query: str, limit: int = 10, **kwargs
    ) -> list[SearchResult]:
        if not self.is_configured():
            raise ValueError("SearXNG host not configured")

        raise NotImplementedError(
            "SearXNG search requires aiohttp call to the configured host"
        )

    def is_configured(self) -> bool:
        return bool(self._host)


class SearchProviderManager:
    """Manages multiple search backends with fallback."""

    def __init__(self) -> None:
        self._backends: dict[SearchProvider, SearchBackend] = {}
        self._default: SearchProvider = SearchProvider.DEFAULT
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._backends[SearchProvider.EXA] = ExaSearch()
        self._backends[SearchProvider.TAVILY] = TavilySearch()
        self._backends[SearchProvider.FIRECRAWL] = FirecrawlSearch()
        self._backends[SearchProvider.SEARXNG] = SearXNGSearch()

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
            "Set one of: EXA_API_KEY, TAVILY_API_KEY, FIRECRAWL_API_KEY, SEARXNG_HOST"
        )

    def available_providers(self) -> list[SearchProvider]:
        """Return list of configured (available) providers."""
        return [p for p, b in self._backends.items() if b.is_configured()]

    def register(self, name: SearchProvider, backend: SearchBackend) -> None:
        """Register a custom search backend."""
        self._backends[name] = backend
