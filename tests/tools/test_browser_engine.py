"""Tests for BrowserEngine unified entry point."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def engine():
    from breadmind.tools.browser_engine import BrowserEngine
    e = BrowserEngine.__new__(BrowserEngine)
    e._session_mgr = MagicMock()
    e._network_monitors = {}
    e._a11y_extractors = {}
    e._default_timeout = 10000
    return e


async def test_session_create(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_session.name = "test"
    mock_session.to_dict.return_value = {"id": "s1", "name": "test"}
    engine._session_mgr.create = AsyncMock(return_value=mock_session)
    result = await engine.handle_session(action="create", name="test", mode="playwright")
    assert "s1" in result


async def test_session_list(engine):
    engine._session_mgr.list_sessions.return_value = [
        {"id": "s1", "name": "a", "mode": "playwright", "persistent": True, "tab_count": 2},
    ]
    result = await engine.handle_session(action="list")
    assert "s1" in result
    assert "a" in result


async def test_session_close(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_session.name = "test"
    engine._resolve_session = MagicMock(return_value=mock_session)
    engine._session_mgr.close = AsyncMock()
    result = await engine.handle_session(action="close", session="s1")
    engine._session_mgr.close.assert_called_once_with("s1")
    assert "Closed" in result


async def test_resolve_session_by_name(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    engine._session_mgr.get.return_value = None
    engine._session_mgr.get_by_name.return_value = mock_session
    result = engine._resolve_session("my-session")
    assert result is mock_session


async def test_navigate(engine):
    mock_session = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://example.com"
    mock_page.title = AsyncMock(return_value="Example")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_session.page = mock_page
    mock_session.touch = MagicMock()
    mock_session.name = "test"
    engine._resolve_session_or_create = AsyncMock(return_value=mock_session)
    result = await engine.navigate(session="s1", url="https://example.com")
    assert "example.com" in result.lower()


async def test_get_a11y_tree(engine):
    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_session.name = "test"
    mock_page = AsyncMock()
    mock_session.page = mock_page
    mock_session.touch = MagicMock()
    engine._resolve_session_or_create = AsyncMock(return_value=mock_session)
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock(return_value={
        "nodes": [{
            "role": {"value": "RootWebArea"}, "name": {"value": "Page"},
            "properties": [], "children": [{
                "role": {"value": "button"}, "name": {"value": "OK"},
                "properties": [], "children": [],
            }],
        }],
    })
    with patch("breadmind.tools.browser_engine.get_cdp_session", return_value=mock_cdp):
        result = await engine.get_a11y_tree(session="s1")
    assert "button" in result
    assert "OK" in result


async def test_get_tool_definitions():
    from breadmind.tools.browser_engine import BrowserEngine
    e = BrowserEngine.__new__(BrowserEngine)
    e._session_mgr = MagicMock()
    e._network_monitors = {}
    e._a11y_extractors = {}
    e._default_timeout = 10000
    tools = e.get_tool_functions()
    names = [f.__name__ for f in tools]
    assert "browser_session" in names
    assert "browser_navigate" in names
    assert "browser_action" in names
    assert "browser_screenshot" in names
    assert "browser_a11y_tree" in names
    assert "browser_network" in names
    assert len(tools) == 6
