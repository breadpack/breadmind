"""Conversation summarizer for context window management."""
from __future__ import annotations

import logging
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
        provider: LLMProvider,
        model: str = "",
        keep_recent: int = 10,
        target_ratio: float = 0.7,
    ):
        self._provider = provider
        self._model = model
        self._keep_recent = keep_recent
        self._target_ratio = target_ratio

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

        # Build summary text from old messages
        parts = []
        for m in old:
            if m.content and m.role in ("user", "assistant"):
                label = "User" if m.role == "user" else "Assistant"
                parts.append(f"{label}: {m.content[:500]}")
            elif m.role == "tool" and m.content:
                parts.append(f"Tool result: {m.content[:300]}")
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

        summary_msg = LLMMessage(
            role="system",
            content=f"[Earlier conversation summary]\n{summary_content}",
        )
        return system_msgs + [summary_msg] + recent
