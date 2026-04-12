"""Tests for the streaming break-preference algorithm."""
from __future__ import annotations

import pytest

from breadmind.messenger.streaming import (
    StreamConfig,
    TelegramStreamAdapter,
)


@pytest.fixture
def adapter() -> TelegramStreamAdapter:
    return TelegramStreamAdapter(StreamConfig(max_chars=50))


def test_break_at_paragraph(adapter: TelegramStreamAdapter):
    text = "Hello world.\n\nSecond paragraph that goes on and on and on."
    pos = adapter._find_break_point(text, 50)
    assert text[:pos].endswith("\n\n")


def test_break_at_newline(adapter: TelegramStreamAdapter):
    text = "Hello world.\nSecond line that is quite long indeed here."
    pos = adapter._find_break_point(text, 50)
    assert text[:pos].endswith("\n")


def test_break_at_sentence(adapter: TelegramStreamAdapter):
    text = "Hello world. This is a sentence that extends past the limit here."
    pos = adapter._find_break_point(text, 50)
    # Should break after ". "
    assert text[:pos].rstrip().endswith(".")


def test_break_at_whitespace(adapter: TelegramStreamAdapter):
    text = "Helloworld-nospaces buthere arespacesnearend ok."
    pos = adapter._find_break_point(text, 45)
    # Should break at a space
    assert text[pos - 1] == " " or pos == 45


def test_hard_break(adapter: TelegramStreamAdapter):
    text = "x" * 100  # No break points at all
    pos = adapter._find_break_point(text, 50)
    assert pos == 50


def test_code_fence_close_reopen(adapter: TelegramStreamAdapter):
    adapter._config.max_chars = 30
    text = "```python\nprint('hello')\nmore code here and more stuff"
    result = adapter._truncate(text)
    # The text is longer than 30 chars and contains an unclosed code fence
    if len(text) > 30:
        assert result.endswith("```")


def test_break_preference_hierarchy():
    """Verify that paragraph breaks are preferred over newlines, etc."""
    adapter = TelegramStreamAdapter(StreamConfig(max_chars=60))
    text = "Line one.\nLine two.\n\nParagraph two which is much longer."
    pos = adapter._find_break_point(text, 60)
    # Should prefer the paragraph break (\n\n) at position 20
    chunk = text[:pos]
    assert "\n\n" in chunk
    assert chunk.endswith("\n\n") or chunk.rstrip().endswith("\n")
