"""Tests for search provider backends and manager."""
from __future__ import annotations

import pytest

from breadmind.tools.search_providers import (
    SearchBackend,
    SearchProvider,
    SearchProviderManager,
    SearchResult,
)


# --- SearchResult ---


def test_search_result_defaults():
    r = SearchResult(title="Test", url="https://example.com", snippet="A test")
    assert r.title == "Test"
    assert r.score == 0.0
    assert r.date == ""
    assert r.metadata == {}


# --- SearchProviderManager ---


def test_manager_no_available_by_default():
    manager = SearchProviderManager()
    assert manager.available_providers() == []


def test_manager_set_default():
    manager = SearchProviderManager()
    manager.set_default(SearchProvider.DEFAULT)
    assert manager._default == SearchProvider.DEFAULT


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
    manager.register(SearchProvider.DEFAULT, FakeBackend())

    results = await manager.search("hello")
    assert len(results) == 1
    assert results[0].title == "Fake"
    assert results[0].snippet == "hello"


async def test_manager_search_uses_specified_provider():
    class FakeSearch(SearchBackend):
        async def search(self, query, limit=10, **kwargs):
            return [SearchResult(title="Result", url="http://test", snippet=query)]

        def is_configured(self):
            return True

    manager = SearchProviderManager()
    manager.register(SearchProvider.DEFAULT, FakeSearch())

    results = await manager.search("query", provider=SearchProvider.DEFAULT)
    assert len(results) == 1
    assert results[0].title == "Result"


def test_manager_register_custom_backend():
    class Custom(SearchBackend):
        async def search(self, query, limit=10, **kwargs):
            return []

        def is_configured(self):
            return True

    manager = SearchProviderManager()
    manager.register(SearchProvider.DEFAULT, Custom())
    assert SearchProvider.DEFAULT in manager.available_providers()
