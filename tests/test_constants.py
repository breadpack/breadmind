from breadmind.constants import (
    DEFAULT_REDIS_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_WEB_PORT,
    DEFAULT_MODEL,
    THINKING_MAX_TOKENS,
)


def test_constants_are_accessible():
    assert DEFAULT_REDIS_URL == "redis://localhost:6379/0"
    assert DEFAULT_MAX_TOKENS == 4096
    assert isinstance(DEFAULT_CLAUDE_MODEL, str)
    assert DEFAULT_WEB_PORT == 8080


def test_model_constants():
    assert DEFAULT_MODEL == "gemini-2.5-flash"
    assert THINKING_MAX_TOKENS == 16384
