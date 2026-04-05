"""Tests for breadmind.core.exporter."""
from __future__ import annotations

import json

import pytest
import yaml

from breadmind.core.exporter import (
    EXPORT_VERSION,
    AgentConfigExporter,
    ConversationExporter,
)
from breadmind.core.protocols.provider import Message, ToolCallRequest
from breadmind.sdk.agent import (
    Agent,
    AgentConfig,
    MemoryConfig,
    PromptConfig,
    SafetyConfig,
)


# ── Fixtures ───────────────────────────────────────────────────────


def _sample_messages() -> list[Message]:
    return [
        Message(role="user", content="Hello, how are you?"),
        Message(role="assistant", content="I'm fine, thanks!"),
    ]


def _sample_metadata() -> dict:
    return {
        "session_id": "sess-001",
        "user": "tester",
        "title": "Test Conversation",
    }


def _messages_with_tool_calls() -> list[Message]:
    return [
        Message(role="user", content="Run a shell command"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="tc-1",
                    name="shell_exec",
                    arguments={"command": "echo hello"},
                ),
            ],
        ),
        Message(
            role="tool",
            content="hello",
            tool_call_id="tc-1",
            name="shell_exec",
        ),
        Message(role="assistant", content="The command returned: hello"),
    ]


# ── test_conversation_to_json ──────────────────────────────────────


def test_conversation_to_json():
    messages = _sample_messages()
    metadata = _sample_metadata()
    result = ConversationExporter.to_json(messages, metadata)

    doc = json.loads(result)
    assert doc["version"] == EXPORT_VERSION
    assert "exported_at" in doc
    assert doc["metadata"]["session_id"] == "sess-001"
    assert doc["metadata"]["user"] == "tester"
    assert len(doc["messages"]) == 2
    assert doc["messages"][0]["role"] == "user"
    assert doc["messages"][0]["content"] == "Hello, how are you?"
    assert doc["messages"][1]["role"] == "assistant"


# ── test_conversation_to_markdown ──────────────────────────────────


def test_conversation_to_markdown():
    messages = _sample_messages()
    metadata = _sample_metadata()
    result = ConversationExporter.to_markdown(messages, metadata)

    assert "# Conversation: Test Conversation" in result
    assert "**Session**: sess-001" in result
    assert "**User**: tester" in result
    assert "## User" in result
    assert "Hello, how are you?" in result
    assert "## Assistant" in result
    assert "I'm fine, thanks!" in result


# ── test_conversation_from_json ────────────────────────────────────


def test_conversation_from_json():
    original_messages = _sample_messages()
    metadata = _sample_metadata()
    exported = ConversationExporter.to_json(original_messages, metadata)

    messages, meta = ConversationExporter.from_json(exported)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello, how are you?"
    assert messages[1].role == "assistant"
    assert meta["session_id"] == "sess-001"


# ── test_conversation_roundtrip ────────────────────────────────────


def test_conversation_roundtrip():
    original = _messages_with_tool_calls()
    metadata = _sample_metadata()

    exported_1 = ConversationExporter.to_json(original, metadata)
    messages, meta = ConversationExporter.from_json(exported_1)
    exported_2 = ConversationExporter.to_json(messages, meta)

    doc1 = json.loads(exported_1)
    doc2 = json.loads(exported_2)

    # Messages and metadata must match; exported_at will differ
    assert doc1["messages"] == doc2["messages"]
    assert doc1["metadata"] == doc2["metadata"]


# ── test_agent_config_to_yaml ──────────────────────────────────────


def test_agent_config_to_yaml():
    agent = Agent(
        name="TestAgent",
        config=AgentConfig(provider="claude", model="claude-sonnet-4-6", max_turns=5),
        prompt=PromptConfig(persona="friendly", language="en"),
        memory=MemoryConfig(working=True, episodic=True),
        safety=SafetyConfig(autonomy="full", blocked_patterns=["rm -rf /"]),
        tools=["shell_exec", "file_read"],
    )

    yaml_str = AgentConfigExporter.to_yaml(agent)
    data = yaml.safe_load(yaml_str)

    assert data["name"] == "TestAgent"
    assert data["config"]["provider"] == "claude"
    assert data["config"]["model"] == "claude-sonnet-4-6"
    assert data["config"]["max_turns"] == 5
    assert data["prompt"]["persona"] == "friendly"
    assert data["prompt"]["language"] == "en"
    assert data["memory"]["working"] is True
    assert data["memory"]["episodic"] is True
    assert data["safety"]["autonomy"] == "full"
    assert data["safety"]["blocked_patterns"] == ["rm -rf /"]
    assert data["tools"]["include"] == ["shell_exec", "file_read"]


# ── test_agent_config_from_yaml ────────────────────────────────────


def test_agent_config_from_yaml():
    yaml_str = """
name: FromYAML
config:
  provider: gemini
  model: gemini-pro
  max_turns: 8
prompt:
  persona: professional
  language: ko
memory:
  working: true
safety:
  autonomy: confirm-destructive
"""
    data = AgentConfigExporter.from_yaml(yaml_str)
    assert data["name"] == "FromYAML"
    assert data["config"]["provider"] == "gemini"
    assert data["config"]["model"] == "gemini-pro"
    assert data["prompt"]["language"] == "ko"


# ── test_export_empty_conversation ─────────────────────────────────


def test_export_empty_conversation():
    messages: list[Message] = []
    metadata = {"session_id": "empty-sess"}

    json_out = ConversationExporter.to_json(messages, metadata)
    doc = json.loads(json_out)
    assert doc["messages"] == []

    md_out = ConversationExporter.to_markdown(messages, metadata)
    assert "# Conversation:" in md_out

    # Roundtrip
    imported_msgs, imported_meta = ConversationExporter.from_json(json_out)
    assert imported_msgs == []
    assert imported_meta["session_id"] == "empty-sess"


# ── test_export_with_tool_calls ────────────────────────────────────


def test_export_with_tool_calls():
    messages = _messages_with_tool_calls()
    metadata = _sample_metadata()

    json_out = ConversationExporter.to_json(messages, metadata)
    doc = json.loads(json_out)

    # Second message should have tool_calls
    assistant_msg = doc["messages"][1]
    assert "tool_calls" in assistant_msg
    assert len(assistant_msg["tool_calls"]) == 1
    assert assistant_msg["tool_calls"][0]["name"] == "shell_exec"
    assert assistant_msg["tool_calls"][0]["arguments"] == {"command": "echo hello"}

    # Tool result message should have tool_call_id
    tool_msg = doc["messages"][2]
    assert tool_msg["tool_call_id"] == "tc-1"
    assert tool_msg["name"] == "shell_exec"

    # Roundtrip check
    imported, _ = ConversationExporter.from_json(json_out)
    assert len(imported) == 4
    assert imported[1].tool_calls[0].name == "shell_exec"
    assert imported[2].tool_call_id == "tc-1"


# ── test_markdown_special_chars ────────────────────────────────────


def test_markdown_special_chars():
    messages = [
        Message(role="user", content="Use `code` and **bold** and <html> tags & symbols"),
        Message(role="assistant", content="Here's a | pipe | table\n---\nAnd a [link](url)"),
    ]
    metadata = {"session_id": "special", "title": "Special <chars> & \"quotes\""}

    md = ConversationExporter.to_markdown(messages, metadata)

    # Content should be preserved as-is (not double-escaped)
    assert "`code`" in md
    assert "**bold**" in md
    assert "<html>" in md
    assert "& symbols" in md
    assert "| pipe |" in md
    # Title should appear in heading
    assert 'Special <chars> & "quotes"' in md


# ── Error handling ─────────────────────────────────────────────────


def test_from_json_invalid_json():
    with pytest.raises(ValueError, match="Invalid JSON"):
        ConversationExporter.from_json("not json at all")


def test_from_json_missing_messages():
    with pytest.raises(ValueError, match="'messages'"):
        ConversationExporter.from_json('{"version": "1.0"}')


def test_from_yaml_invalid_yaml():
    with pytest.raises(ValueError, match="Invalid YAML"):
        AgentConfigExporter.from_yaml(":\n  :\n    - :\n  bad:\n - broken")


def test_from_yaml_non_mapping():
    with pytest.raises(ValueError, match="mapping"):
        AgentConfigExporter.from_yaml("- just\n- a\n- list")
