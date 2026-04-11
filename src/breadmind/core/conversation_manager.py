"""Manages conversation history, context enrichment, and token budgets."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from breadmind.llm.base import LLMMessage

if TYPE_CHECKING:
    from breadmind.memory.working import WorkingMemory

logger = logging.getLogger("breadmind.agent")


class ConversationManager:
    """Handles message history assembly, context enrichment, and summarization.

    Extracted from CoreAgent.handle_message() to separate conversation
    management concerns from the agent's main orchestration loop.
    """

    def __init__(
        self,
        working_memory: WorkingMemory | None = None,
        context_builder: Any | None = None,
        summarizer: Any | None = None,
    ):
        self._working_memory = working_memory
        self._context_builder = context_builder
        self._summarizer = summarizer

    @property
    def working_memory(self) -> WorkingMemory | None:
        return self._working_memory

    @working_memory.setter
    def working_memory(self, value: WorkingMemory | None) -> None:
        self._working_memory = value

    @property
    def context_builder(self) -> Any | None:
        return self._context_builder

    @context_builder.setter
    def context_builder(self, value: Any | None) -> None:
        self._context_builder = value

    @property
    def summarizer(self) -> Any | None:
        return self._summarizer

    @summarizer.setter
    def summarizer(self, value: Any | None) -> None:
        self._summarizer = value

    def build_messages(
        self,
        session_id: str,
        user_message: str,
        system_prompt: str,
        *,
        user: str = "",
        channel: str = "",
    ) -> list[LLMMessage]:
        """Build the initial message list from system prompt, history, and user input.

        If working_memory is available, includes previous conversation messages
        and stores a sanitized copy of the user message.

        Returns the assembled message list ready for context enrichment.
        """
        import json as _json

        system_msg = LLMMessage(role="system", content=system_prompt)
        user_msg = LLMMessage(role="user", content=user_message)

        if self._working_memory is not None:
            session = self._working_memory.get_or_create_session(
                session_id, user=user, channel=channel,
            )
            previous_messages = list(session.messages)
            logger.info(_json.dumps({
                "event": "context_build",
                "session": session_id,
                "previous_msgs": len(previous_messages),
            }))
            messages = [system_msg] + previous_messages + [user_msg]
            # Save a sanitized version of the user message to memory
            from breadmind.storage.credential_vault import CredentialVault
            clean_content = CredentialVault.sanitize_text(user_message)
            stored_user_msg = LLMMessage(role="user", content=clean_content)
            self._working_memory.add_message(session_id, stored_user_msg)
        else:
            messages = [system_msg, user_msg]

        return messages

    async def enrich_context(
        self,
        messages: list[LLMMessage],
        session_id: str,
        user_message: str,
        system_prompt: str,
        *,
        intent: Any | None = None,
    ) -> list[LLMMessage]:
        """Enrich messages with context from the context builder.

        Inserts context system messages after the system prompt but before
        conversation history. Returns the enriched message list (or original
        if no context_builder or on failure).
        """
        if not self._context_builder:
            return messages

        try:
            enrichment = await asyncio.wait_for(
                self._context_builder.build_context(session_id, user_message, intent=intent),
                timeout=10,
            )
            # Extract only the enrichment system messages (not conversation history)
            context_msgs = [
                m for m in enrichment
                if m.role == "system" and m.content and m.content != system_prompt
            ]
            if context_msgs:
                # Insert context after system prompt, before conversation history
                messages = [messages[0]] + context_msgs + messages[1:]
        except Exception as e:
            logger.warning(f"ContextBuilder enrichment failed: {e}")

        return messages

    async def maybe_summarize(
        self,
        messages: list[LLMMessage],
        tools: list,
        provider: Any | None = None,
    ) -> list[LLMMessage]:
        """Apply conversation summarization or token trimming if needed.

        Uses the summarizer if available, otherwise falls back to
        TokenCounter-based trimming to fit the context window.

        Returns the (possibly trimmed) message list.
        """
        if self._summarizer is not None and hasattr(self._summarizer, "summarize_if_needed"):
            try:
                return await self._summarizer.summarize_if_needed(messages, tools)
            except Exception:
                logger.exception("Summarizer error, using original messages")
                return messages

        # Fallback: trim messages if exceeding context window
        try:
            from breadmind.llm.token_counter import TokenCounter
            model = getattr(provider, "model_name", "claude-sonnet-4-6")
            if not TokenCounter.fits_in_context(messages, tools, model):
                trimmed = TokenCounter.trim_messages_to_fit(messages, tools, model)
                logger.warning("Trimmed messages to fit context window")
                return trimmed
        except Exception:
            logger.debug("TokenCounter check skipped due to error")

        return messages

    def store_assistant_message(self, session_id: str, content: str) -> None:
        """Store an assistant response in working memory if available."""
        if self._working_memory is not None:
            self._working_memory.add_message(
                session_id,
                LLMMessage(role="assistant", content=content),
            )

    def store_message(self, session_id: str, message: LLMMessage) -> None:
        """Store an arbitrary message in working memory if available."""
        if self._working_memory is not None:
            self._working_memory.add_message(session_id, message)
