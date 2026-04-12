"""Tests for the HTTP session pool manager."""
from __future__ import annotations


import aiohttp
import pytest

from breadmind.core.http_pool import (
    HTTPPoolConfig,
    HTTPSessionManager,
    get_session_manager,
    _reset_session_manager,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a fresh singleton."""
    _reset_session_manager()
    yield
    _reset_session_manager()


# ── Config defaults ─────────────────────────────────────────────────


def test_config_defaults():
    cfg = HTTPPoolConfig()
    assert cfg.total_limit == 100
    assert cfg.per_host_limit == 30
    assert cfg.dns_cache_ttl == 300
    assert cfg.keepalive_timeout == 30
    assert cfg.connect_timeout == 10.0


# ── Session creation / reuse ────────────────────────────────────────


async def test_get_session_creates_new():
    mgr = HTTPSessionManager()
    session = await mgr.get_session("test")
    assert isinstance(session, aiohttp.ClientSession)
    assert not session.closed
    await mgr.close_all()


async def test_get_session_reuses():
    mgr = HTTPSessionManager()
    s1 = await mgr.get_session("reuse")
    s2 = await mgr.get_session("reuse")
    assert s1 is s2
    await mgr.close_all()


async def test_multiple_named_sessions():
    mgr = HTTPSessionManager()
    gemini = await mgr.get_session("gemini")
    ollama = await mgr.get_session("ollama")
    default = await mgr.get_session("default")

    assert gemini is not ollama
    assert gemini is not default
    assert ollama is not default
    await mgr.close_all()


# ── Close ───────────────────────────────────────────────────────────


async def test_close_session():
    mgr = HTTPSessionManager()
    session = await mgr.get_session("closable")
    assert not session.closed

    await mgr.close_session("closable")
    assert session.closed

    # Getting the same name again should create a new session.
    new_session = await mgr.get_session("closable")
    assert new_session is not session
    assert not new_session.closed
    await mgr.close_all()


async def test_close_all():
    mgr = HTTPSessionManager()
    s1 = await mgr.get_session("a")
    s2 = await mgr.get_session("b")

    await mgr.close_all()

    assert s1.closed
    assert s2.closed

    # Stats should be empty after close_all.
    assert mgr.get_stats() == {}


# ── Stats ───────────────────────────────────────────────────────────


async def test_get_stats():
    mgr = HTTPSessionManager()
    await mgr.get_session("alpha")
    await mgr.get_session("beta")

    stats = mgr.get_stats()
    assert "alpha" in stats
    assert "beta" in stats
    assert stats["alpha"]["closed"] is False
    assert "limit" in stats["alpha"]
    await mgr.close_all()


# ── Singleton ───────────────────────────────────────────────────────


def test_singleton():
    m1 = get_session_manager()
    m2 = get_session_manager()
    assert m1 is m2


def test_singleton_ignores_subsequent_config():
    cfg = HTTPPoolConfig(total_limit=42)
    m1 = get_session_manager(cfg)
    m2 = get_session_manager(HTTPPoolConfig(total_limit=999))
    assert m1 is m2
    assert m1._config.total_limit == 42
