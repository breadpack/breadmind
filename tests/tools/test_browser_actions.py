"""Tests for advanced browser actions."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example")
    page.evaluate = AsyncMock(return_value={"key": "value"})
    locator = AsyncMock()
    locator.first = locator
    page.locator = MagicMock(return_value=locator)
    page.query_selector = AsyncMock(return_value=AsyncMock())
    return page


async def test_hover(mock_page):
    from breadmind.tools.browser_actions import hover
    result = await hover(mock_page, selector="#btn")
    mock_page.hover.assert_called_once_with("#btn", timeout=10000)
    assert "Hovered" in result


async def test_drag_drop(mock_page):
    from breadmind.tools.browser_actions import drag_drop
    result = await drag_drop(mock_page, source="#a", target="#b")
    mock_page.drag_and_drop.assert_called_once_with("#a", "#b", timeout=10000)
    assert "Dragged" in result


async def test_upload_file(mock_page):
    from breadmind.tools.browser_actions import upload_file
    mock_input = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=mock_input)
    result = await upload_file(mock_page, selector="input[type=file]", file_paths=["/tmp/test.txt"])
    mock_input.set_input_files.assert_called_once_with(["/tmp/test.txt"])
    assert "Uploaded" in result


async def test_upload_file_element_not_found(mock_page):
    from breadmind.tools.browser_actions import upload_file
    mock_page.query_selector = AsyncMock(return_value=None)
    result = await upload_file(mock_page, selector="input[type=file]", file_paths=["/tmp/x.txt"])
    assert "[error]" in result


async def test_select_option(mock_page):
    from breadmind.tools.browser_actions import select_option
    mock_page.select_option = AsyncMock(return_value=["opt1"])
    result = await select_option(mock_page, selector="select#lang", value="ko")
    mock_page.select_option.assert_called_once()
    assert "Selected" in result


async def test_scroll_down(mock_page):
    from breadmind.tools.browser_actions import scroll
    result = await scroll(mock_page, direction="down", amount=500)
    mock_page.evaluate.assert_called_once()
    assert "Scrolled" in result


async def test_press_key(mock_page):
    from breadmind.tools.browser_actions import press_key
    result = await press_key(mock_page, key="Enter")
    mock_page.keyboard.press.assert_called_once_with("Enter")
    assert "Pressed" in result


async def test_get_cookies(mock_page):
    from breadmind.tools.browser_actions import get_cookies
    mock_page.context.cookies = AsyncMock(return_value=[{"name": "sid", "value": "abc"}])
    result = await get_cookies(mock_page)
    assert isinstance(result, list)
    assert result[0]["name"] == "sid"


async def test_export_pdf(mock_page):
    from breadmind.tools.browser_actions import export_pdf
    mock_page.pdf = AsyncMock(return_value=b"%PDF-fake")
    result = await export_pdf(mock_page)
    assert "PDF" in result
