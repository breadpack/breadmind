"""Tests for VisionBrowser high-level vision tools."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_analyzer():
    analyzer = AsyncMock()
    analyzer.analyze_page = AsyncMock(return_value="Login page with email and password fields")
    analyzer.find_element = AsyncMock(return_value='[textbox "Email"]')
    return analyzer


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.do_action = AsyncMock(return_value="Clicked: [textbox \"Email\"]")
    engine.navigate = AsyncMock(return_value="Navigated to: https://example.com")
    return engine


@pytest.fixture
def vision(mock_analyzer, mock_engine):
    from breadmind.tools.browser_vision import VisionBrowser
    return VisionBrowser(mock_analyzer, mock_engine)


async def test_analyze(vision):
    result = await vision.analyze(session="s1", question="What page is this?")
    assert "Login" in result


async def test_find_element(vision):
    result = await vision.find_element(session="s1", description="email input")
    assert "Email" in result


async def test_smart_click(vision, mock_engine):
    result = await vision.smart_click(session="s1", description="the sign in button")
    mock_engine.do_action.assert_called_once()
    assert len(result) > 0


async def test_smart_fill(vision, mock_engine):
    result = await vision.smart_fill(session="s1", description="email field", value="test@test.com")
    assert mock_engine.do_action.call_count >= 1
    assert len(result) > 0


async def test_get_tool_functions(vision):
    tools = vision.get_tool_functions()
    names = [f.__name__ for f in tools]
    assert "browser_analyze" in names
    assert "browser_find_element" in names
    assert "browser_smart_click" in names
    assert "browser_smart_fill" in names
    assert len(tools) == 4
