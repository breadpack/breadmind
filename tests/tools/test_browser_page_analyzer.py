"""Tests for PageAnalyzer — LLM Vision page analysis."""
from __future__ import annotations

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.llm.base import LLMResponse, TokenUsage


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="This is a login page with email and password fields and a Sign In button.",
        tool_calls=[], usage=TokenUsage(input_tokens=500, output_tokens=50), stop_reason="end_turn",
    ))
    return provider


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.screenshot = AsyncMock(return_value=(
        f"Screenshot (1024 bytes)\nURL: https://example.com\nTitle: Login\n"
        f"[screenshot_base64]{base64.b64encode(b'fake-png').decode()}[/screenshot_base64]"
    ))
    engine.get_a11y_tree = AsyncMock(return_value=(
        'Accessibility Tree (~20 tokens):\n'
        '[textbox "Email" value=""]\n'
        '[textbox "Password" value="" type=password]\n'
        '[button "Sign In"]'
    ))
    return engine


async def test_analyze_page(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.analyze_page(session="s1", question="What is on this page?")
    assert "login" in result.lower()
    mock_provider.chat.assert_called_once()
    call_args = mock_provider.chat.call_args
    messages = call_args[0][0]
    has_image = any(a.type == "image" for m in messages for a in m.attachments)
    assert has_image


async def test_find_element(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    mock_provider.chat = AsyncMock(return_value=LLMResponse(
        content='[textbox "Email"]', tool_calls=[],
        usage=TokenUsage(input_tokens=400, output_tokens=20), stop_reason="end_turn",
    ))
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.find_element(session="s1", description="the email input field")
    assert "Email" in result


async def test_analyze_page_no_question(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.analyze_page(session="s1")
    assert len(result) > 0


async def test_build_vision_prompt():
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    prompt = PageAnalyzer.build_analysis_prompt(
        a11y_tree='[button "OK"]', question="What button is on the page?", network_summary=None,
    )
    assert "button" in prompt.lower()
    assert "What button" in prompt
