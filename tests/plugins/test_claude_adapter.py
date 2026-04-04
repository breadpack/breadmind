import pytest
from unittest.mock import MagicMock
from breadmind.core.protocols import Message, PromptBlock
from breadmind.plugins.v2_builtin.providers.claude_adapter import ClaudeAdapter

@pytest.fixture
def adapter():
    return ClaudeAdapter(api_key="test-key", model="claude-sonnet-4-6")

def test_supports_feature(adapter):
    assert adapter.supports_feature("thinking_blocks") is True
    assert adapter.supports_feature("system_reminder") is True
    assert adapter.supports_feature("prompt_caching") is True
    assert adapter.supports_feature("tool_search") is True
    assert adapter.supports_feature("nonexistent") is False

def test_get_cache_strategy(adapter):
    strategy = adapter.get_cache_strategy()
    assert strategy is not None
    assert strategy.name == "claude_ephemeral"

def test_transform_system_prompt_cacheable(adapter):
    blocks = [
        PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0,
                    provider_hints={"claude": {"scope": "global"}}),
        PromptBlock(section="env", content="OS: Linux", cacheable=False, priority=5),
    ]
    result = adapter.transform_system_prompt(blocks)
    assert len(result) == 2
    assert result[0]["cache_control"]["scope"] == "global"
    assert "cache_control" not in result[1]

def test_transform_messages_basic(adapter):
    messages = [Message(role="user", content="hello"), Message(role="system", content="prompt")]
    result = adapter.transform_messages(messages)
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "system"

def test_fallback_none(adapter):
    assert adapter.fallback is None

def test_fallback_set():
    fb = MagicMock()
    a = ClaudeAdapter(api_key="test", model="claude-sonnet-4-6", fallback_provider=fb)
    assert a.fallback is fb
