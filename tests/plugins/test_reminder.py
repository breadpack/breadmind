"""Tests for ReminderInjector."""
from unittest.mock import MagicMock
from breadmind.plugins.builtin.prompt_builder.reminder import ReminderInjector


def test_inject_claude_style():
    """Test Claude-style system reminder injection."""
    provider = MagicMock()
    provider.supports_feature.return_value = True
    injector = ReminderInjector()
    msg = injector.inject("memory", "User prefers Korean.", provider)
    assert msg.role == "user"
    assert "<system-reminder>" in msg.content
    assert "# memory" in msg.content
    assert msg.is_meta is True


def test_inject_generic_style():
    """Test generic-style context injection for non-Claude providers."""
    provider = MagicMock()
    provider.supports_feature.return_value = False
    injector = ReminderInjector()
    msg = injector.inject("memory", "User prefers Korean.", provider)
    assert msg.role == "system"
    assert "[Context: memory]" in msg.content
    assert msg.is_meta is True
