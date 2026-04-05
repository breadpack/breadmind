"""Conversation and agent config export/import utilities."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import yaml

from breadmind.core.protocols.provider import Message, ToolCallRequest

logger = logging.getLogger(__name__)

EXPORT_VERSION = "1.0"


# ── Conversation Exporter ──────────────────────────────────────────


class ConversationExporter:
    """Export/import conversations in JSON and Markdown formats."""

    # ── JSON export ────────────────────────────────────────────────

    @staticmethod
    def to_json(messages: list[Message], metadata: dict[str, Any]) -> str:
        """Serialize a conversation to a JSON string.

        Parameters
        ----------
        messages:
            Ordered list of conversation messages.
        metadata:
            Must contain at least ``session_id``.  ``user`` and ``title``
            are recommended.

        Returns
        -------
        str
            Pretty-printed JSON document.
        """
        serialized: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                entry["content"] = msg.content
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id is not None:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name is not None:
                entry["name"] = msg.name
            serialized.append(entry)

        document = {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            "messages": serialized,
        }
        return json.dumps(document, ensure_ascii=False, indent=2, default=str)

    # ── Markdown export ────────────────────────────────────────────

    @staticmethod
    def to_markdown(messages: list[Message], metadata: dict[str, Any]) -> str:
        """Render a conversation as a human-readable Markdown document.

        Markdown export is **read-only** -- there is no ``from_markdown``.
        """
        title = metadata.get("title", "Untitled")
        session_id = metadata.get("session_id", "unknown")
        user = metadata.get("user", "unknown")
        date = metadata.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        lines: list[str] = [
            f"# Conversation: {title}",
            f"**Session**: {session_id} | **User**: {user} | **Date**: {date}",
            "",
            "---",
            "",
        ]

        for msg in messages:
            role_label = msg.role.capitalize()
            lines.append(f"## {role_label}")
            lines.append("")
            if msg.content is not None:
                # Preserve content as-is (may already contain markdown)
                lines.append(msg.content)
                lines.append("")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    # Summarise each tool call as a blockquote
                    args_summary = json.dumps(tc.arguments, ensure_ascii=False, default=str)
                    if len(args_summary) > 120:
                        args_summary = args_summary[:117] + "..."
                    lines.append(f"> Tool: {tc.name}({args_summary})")
                lines.append("")

        return "\n".join(lines)

    # ── JSON import ────────────────────────────────────────────────

    @staticmethod
    def from_json(data: str) -> tuple[list[Message], dict[str, Any]]:
        """Deserialize a JSON export back into messages and metadata.

        Returns
        -------
        tuple[list[Message], dict[str, Any]]
            ``(messages, metadata)`` extracted from the JSON document.

        Raises
        ------
        ValueError
            If the JSON is malformed or missing required fields.
        """
        try:
            doc = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if not isinstance(doc, dict) or "messages" not in doc:
            raise ValueError("JSON document must contain a 'messages' key")

        metadata = doc.get("metadata", {})
        messages: list[Message] = []
        for entry in doc["messages"]:
            tool_calls = [
                ToolCallRequest(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=tc.get("arguments", {}),
                )
                for tc in entry.get("tool_calls", [])
            ]
            messages.append(
                Message(
                    role=entry["role"],
                    content=entry.get("content"),
                    tool_calls=tool_calls,
                    tool_call_id=entry.get("tool_call_id"),
                    name=entry.get("name"),
                )
            )
        return messages, metadata


# ── Agent Config Exporter ──────────────────────────────────────────


class AgentConfigExporter:
    """Export/import Agent configuration as YAML."""

    @staticmethod
    def export_config(agent) -> dict[str, Any]:
        """Extract the full configuration from an Agent instance as a dict."""
        from breadmind.sdk.agent import Agent

        data: dict[str, Any] = {"name": agent.name}

        # Config
        data["config"] = {
            "provider": agent.config.provider,
            "model": agent.config.model,
            "max_turns": agent.config.max_turns,
        }
        if agent.config.fallback_provider:
            data["config"]["fallback"] = agent.config.fallback_provider

        # Prompt
        data["prompt"] = {
            "persona": agent.prompt.persona,
            "language": agent.prompt.language,
            "persona_name": agent.prompt.persona_name,
        }
        if agent.prompt.role:
            data["prompt"]["role"] = agent.prompt.role
        if agent.prompt.custom_instructions:
            data["prompt"]["custom_instructions"] = agent.prompt.custom_instructions

        # Memory
        data["memory"] = {
            "working": agent.memory_config.working,
            "episodic": agent.memory_config.episodic,
            "semantic": agent.memory_config.semantic,
            "dream": agent.memory_config.dream,
            "max_messages": agent.memory_config.max_messages,
            "compress_threshold": agent.memory_config.compress_threshold,
        }

        # Safety
        data["safety"] = {
            "autonomy": agent.safety_config.autonomy,
        }
        if agent.safety_config.blocked_patterns:
            data["safety"]["blocked_patterns"] = agent.safety_config.blocked_patterns

        # Tools
        if agent.tools:
            data["tools"] = {
                "include": list(agent.tools),
            }
            if agent.safety_config.approve_required:
                data["tools"]["approve_required"] = agent.safety_config.approve_required

        return data

    @classmethod
    def to_yaml(cls, agent) -> str:
        """Export Agent configuration as a YAML string."""
        data = cls.export_config(agent)
        return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @staticmethod
    def from_yaml(yaml_str: str) -> dict[str, Any]:
        """Parse a YAML string into a configuration dict.

        The returned dict can be passed to ``load_agent_yaml``-compatible
        code or used to construct an ``Agent`` manually.

        Raises
        ------
        ValueError
            If the YAML is malformed.
        """
        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("YAML document must be a mapping")
        return data
