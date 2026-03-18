"""Conversation summarizer for context window management."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, LLMProvider
from breadmind.llm.token_counter import TokenCounter

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Summarize this conversation concisely. Keep all key facts, decisions, "
    "tool results, and action items. Output only the summary, no preamble."
)


class ConversationSummarizer:
    """Compress old conversation turns to fit context window."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str = "",
        keep_recent: int = 10,
        target_ratio: float = 0.7,
    ):
        self._provider = provider
        self._model = model
        self._keep_recent = keep_recent
        self._target_ratio = target_ratio

    def extract_domain_references(self, messages: list) -> dict:
        """Extract domain entity references from messages for preservation during summarization."""
        references: dict[str, list[str]] = {
            "tasks": [],
            "events": [],
            "contacts": [],
            "deadlines": [],
        }

        for msg in messages:
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if not content:
                continue

            # Task IDs
            task_ids = re.findall(r'\[ID:\s*([a-f0-9-]{8,})\]', content)
            references["tasks"].extend(task_ids)

            # Event mentions (after 📅 or 일정)
            event_matches = re.findall(r'(?:📅|일정[:\s])\s*(.+?)(?:\n|\(|$)', content)
            references["events"].extend([m.strip() for m in event_matches if m.strip()])

            # Contact mentions
            contact_matches = re.findall(r'(?:📇|연락처[:\s])\s*(.+?)(?:\n|\||$)', content)
            references["contacts"].extend([m.strip() for m in contact_matches if m.strip()])

            # Deadlines
            deadline_matches = re.findall(r'(?:마감|due)[:\s]*(.+?)(?:\n|\)|$)', content, re.I)
            references["deadlines"].extend([m.strip() for m in deadline_matches if m.strip()])

        # Deduplicate while preserving order
        for key in references:
            references[key] = list(dict.fromkeys(references[key]))

        return references

    def format_domain_context(self, references: dict) -> str:
        """Format extracted domain references as a context preservation block."""
        lines = []
        if references["tasks"]:
            lines.append(f"Referenced tasks: {', '.join(references['tasks'])}")
        if references["events"]:
            lines.append(f"Referenced events: {', '.join(references['events'])}")
        if references["contacts"]:
            lines.append(f"Referenced contacts: {', '.join(references['contacts'])}")
        if references["deadlines"]:
            lines.append(f"Deadlines mentioned: {', '.join(references['deadlines'])}")
        if not lines:
            return ""
        return "\n## Domain Context (preserved)\n" + "\n".join(lines)

    async def summarize_if_needed(
        self,
        messages: list[LLMMessage],
        tools: list | None,
        model: str = "",
    ) -> list[LLMMessage]:
        """Return messages, summarizing old turns if they exceed the target ratio of context."""
        effective_model = model or self._model or getattr(self._provider, "model_name", "claude-sonnet-4-6")
        limit = TokenCounter.get_model_limit(effective_model)
        target = int(limit * self._target_ratio)

        current_tokens = TokenCounter.estimate_messages_tokens(messages)
        if tools:
            current_tokens += TokenCounter.estimate_tools_tokens(tools)

        if current_tokens <= target:
            return messages

        # Split: system msgs | old middle | recent
        system_msgs: list[LLMMessage] = []
        idx = 0
        while idx < len(messages) and messages[idx].role == "system":
            system_msgs.append(messages[idx])
            idx += 1

        remaining = messages[idx:]
        if len(remaining) <= self._keep_recent:
            return messages

        old = remaining[: -self._keep_recent]
        recent = remaining[-self._keep_recent :]

        # Build summary text from old messages (sanitize to prevent credential leakage)
        from breadmind.storage.credential_vault import CredentialVault
        parts = []
        for m in old:
            if m.content and m.role in ("user", "assistant"):
                label = "User" if m.role == "user" else "Assistant"
                content = CredentialVault.sanitize_text(m.content[:500])
                parts.append(f"{label}: {content}")
            elif m.role == "tool" and m.content:
                content = CredentialVault.sanitize_text(m.content[:300])
                parts.append(f"Tool result: {content}")
        if not parts:
            return messages

        old_text = "\n".join(parts)
        summary_request = LLMMessage(
            role="user",
            content=f"{_SUMMARY_PROMPT}\n\n{old_text[:8000]}",
        )
        try:
            resp = await self._provider.chat([summary_request])
            summary_content = resp.content or ""
        except Exception:
            logger.warning("Summarization failed, trimming instead")
            return TokenCounter.trim_messages_to_fit(
                messages, tools, effective_model,
            )

        # Preserve domain entity references from summarized messages
        references = self.extract_domain_references(old)
        domain_context = self.format_domain_context(references)
        if domain_context:
            summary_content += domain_context

        summary_msg = LLMMessage(
            role="system",
            content=f"[Earlier conversation summary]\n{summary_content}",
        )
        return system_msgs + [summary_msg] + recent
