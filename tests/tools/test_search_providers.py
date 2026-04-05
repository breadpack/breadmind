"""Tests for search provider backends and manager."""
from __future__ import annotations

import pytest

from breadmind.tools.search_providers import (
    ExaSearch,
    FirecrawlSearch,
    SearchBackend,
    SearchProvider,
    SearchProviderManager,
    SearchResult,
    SearXNGSearch,
    TavilySearch,
)


# --- SearchResult ---


def test_search_result_defaults():
    r = SearchResult(title="Test", url="https://example.com", snippet="A test")
    assert r.title == "Test"
    assert r.score == 0.0
    assert r.date == ""
    assert r.metadata == {}


# --- Backend configuration ---


def test_exa_not_configured_by_default():
    backend = ExaSearch()
    assert backend.is_configured() is False


def test_exa_configured_with_key():
    backend = ExaSearch(api_key="test-key")
    assert backend.is_configured() is True


def test_tavily_not_configured_by_default():
    backend = TavilySearch()
    assert backend.is_configured() is False


def test_tavily_configured_with_key():
    backend = TavilySearch(api_key="test-key")
    assert backend.is_configured() is True


def test_firecrawl_configured_with_key():
    backend = FirecrawlSearch(api_key="fc-key")
    assert backend.is_configured() is True


def test_searxng_configured_with_host():
    backend = SearXNGSearch(host="http://localhost:8888")
    assert backend.is_configured() is True


def test_searxng_not_configured_by_default():
    backend = SearXNGSearch()
    assert backend.is_configured() is False


# --- Backend search raises without config ---


async def test_exa_search_raises_without_key():
    backend = ExaSearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.search("test query")


async def test_tavily_search_raises_without_key():
    backend = TavilySearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.search("test query")


async def test_firecrawl_search_raises_without_key():
    backend = FirecrawlSearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.search("test query")


async def test_searxng_search_raises_without_host():
    backend = SearXNGSearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.search("test query")


# --- SearchProviderManager ---


def test_manager_no_available_by_default():
    manager = SearchProviderManager()
    assert manager.available_providers() == []


def test_manager_available_with_configured_backend():
    manager = SearchProviderManager()
    manager.register(SearchProvider.EXA, ExaSearch(api_key="key"))
    available = manager.available_providers()
    assert SearchProvider.EXA in available


def test_manager_set_default():
    manager = SearchProviderManager()
    manager.set_default(SearchProvider.TAVILY)
    assert manager._default == SearchProvider.TAVILY


async def test_manager_search_raises_when_none_configured():
    manager = SearchProviderManager()
    with pytest.raises(ValueError, match="No search provider"):
        await manager.search("test")


async def test_manager_search_fallback():
    """When default is not configured, manager falls back to first available."""

    class FakeBackend(SearchBackend):
        async def search(self, query, limit=10, **kwargs):
            return [SearchResult(title="Fake", url="http://fake", snippet=query)]

        def is_configured(self):
            return True

    manager = SearchProviderManager()
    manager.set_default(SearchProvider.DEFAULT)
    manager.register(SearchProvider.TAVILY, FakeBackend())

    results = await manager.search("hello")
    assert len(results) == 1
    assert results[0].title == "Fake"
    assert results[0].snippet == "hello"


async def test_manager_search_uses_specified_provider():
    class FakeExa(SearchBackend):
        async def search(self, query, limit=10, **kwargs):
            return [SearchResult(title="Exa Result", url="http://exa", snippet=query)]

        def is_configured(self):
            return True

    manager = SearchProviderManager()
    manager.register(SearchProvider.EXA, FakeExa())

    results = await manager.search("query", provider=SearchProvider.EXA)
    assert len(results) == 1
    assert results[0].title == "Exa Result"


def test_manager_register_custom_backend():
    class Custom(SearchBackend):
        async def search(self, query, limit=10, **kwargs):
            return []

        def is_configured(self):
            return True

    manager = SearchProviderManager()
    manager.register(SearchProvider.DEFAULT, Custom())
    assert SearchProvider.DEFAULT in manager.available_providers()


# --- Tavily/Firecrawl specific methods ---


async def test_tavily_extract_raises_without_key():
    backend = TavilySearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.extract(["http://example.com"])


async def test_firecrawl_scrape_raises_without_key():
    backend = FirecrawlSearch()
    with pytest.raises(ValueError, match="not configured"):
        await backend.scrape("http://example.com")
