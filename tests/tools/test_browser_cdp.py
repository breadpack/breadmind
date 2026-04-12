"""Tests for browser.py CDPSession accessor and page/context exposure."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.is_closed.return_value = False
    ctx = AsyncMock()
    ctx.new_cdp_session = AsyncMock(return_value=MagicMock(name="cdp_session"))
    page.context = ctx
    return page


async def test_get_cdp_session(mock_page):
    from breadmind.tools.browser import get_cdp_session

    session = await get_cdp_session(mock_page)
    mock_page.context.new_cdp_session.assert_called_once_with(mock_page)
    assert session is not None


async def test_get_active_page_returns_none_when_no_browser():
    from breadmind.tools.browser import get_active_page

    import breadmind.tools.browser as bmod
    bmod._page = None
    result = get_active_page()
    assert result is None


async def test_get_active_context_returns_none_when_no_browser():
    from breadmind.tools.browser import get_active_context

    import breadmind.tools.browser as bmod
    bmod._context = None
    result = get_active_context()
    assert result is None
