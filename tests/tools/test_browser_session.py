"""Tests for BrowserSession and SessionManager."""
from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_browser_session_creation():
    from breadmind.tools.browser_session import BrowserSession
    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    assert session.id == "s1"
    assert session.name == "test"
    assert session.persistent is False
    assert session.tabs == {}


def test_browser_session_touch_updates_last_active():
    from breadmind.tools.browser_session import BrowserSession
    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    old = session.last_active
    time.sleep(0.01)
    session.touch()
    assert session.last_active > old


def test_browser_session_is_idle():
    from breadmind.tools.browser_session import BrowserSession
    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    assert not session.is_idle(timeout=300)
    session.last_active = time.time() - 400
    assert session.is_idle(timeout=300)


def test_persistent_session_never_idle():
    from breadmind.tools.browser_session import BrowserSession
    session = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=True, context=MagicMock(), page=AsyncMock(),
    )
    session.last_active = time.time() - 9999
    assert not session.is_idle(timeout=300)


async def test_session_manager_create_session():
    from breadmind.tools.browser_session import SessionManager
    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    mock_page = AsyncMock()
    mock_page.is_closed.return_value = False
    mock_ctx.pages = [mock_page]
    with patch.object(mgr, '_launch_context', return_value=(mock_ctx, mock_page)):
        session = await mgr.create(name="test-session", mode="playwright", persistent=False)
    assert session.name == "test-session"
    assert session.id in mgr._sessions
    assert len(mgr._sessions) == 1


async def test_session_manager_get_session():
    from breadmind.tools.browser_session import SessionManager, BrowserSession
    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    s = BrowserSession(
        id="s1", name="my-session", mode="playwright",
        persistent=False, context=MagicMock(), page=AsyncMock(),
    )
    mgr._sessions["s1"] = s
    assert mgr.get("s1") is s
    assert mgr.get_by_name("my-session") is s
    assert mgr.get("nonexistent") is None


async def test_session_manager_close_session():
    from breadmind.tools.browser_session import SessionManager, BrowserSession
    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    s = BrowserSession(
        id="s1", name="test", mode="playwright",
        persistent=False, context=mock_ctx, page=AsyncMock(),
    )
    mgr._sessions["s1"] = s
    await mgr.close("s1")
    assert "s1" not in mgr._sessions
    mock_ctx.close.assert_called_once()


async def test_session_manager_max_sessions_enforced():
    from breadmind.tools.browser_session import SessionManager
    mgr = SessionManager(max_sessions=2, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    mock_page = AsyncMock()
    mock_page.is_closed.return_value = False
    mock_ctx.pages = [mock_page]
    with patch.object(mgr, '_launch_context', return_value=(mock_ctx, mock_page)):
        await mgr.create(name="s1", mode="playwright", persistent=False)
        await mgr.create(name="s2", mode="playwright", persistent=False)
        with pytest.raises(RuntimeError, match="Maximum sessions"):
            await mgr.create(name="s3", mode="playwright", persistent=False)


async def test_cleanup_idle_transient_sessions():
    from breadmind.tools.browser_session import SessionManager, BrowserSession
    mgr = SessionManager(max_sessions=5, max_tabs=10, idle_timeout=300)
    mock_ctx = AsyncMock()
    s = BrowserSession(
        id="s1", name="temp", mode="playwright",
        persistent=False, context=mock_ctx, page=AsyncMock(),
    )
    s.last_active = time.time() - 400
    mgr._sessions["s1"] = s
    removed = await mgr.cleanup_idle()
    assert "s1" in removed
    assert "s1" not in mgr._sessions
