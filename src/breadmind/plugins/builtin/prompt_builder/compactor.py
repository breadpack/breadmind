"""LLM 기반 컨텍스트 압축기."""
from __future__ import annotations

from typing import Any

from breadmind.core.protocols import Message, CompactResult


class LLMCompactor:
    """대화 히스토리를 LLM으로 압축."""

    def __init__(self, provider: Any, keep_recent: int = 5) -> None:
        self._provider = provider
        self._keep_recent = keep_recent

    async def compact(self, messages: list[Message], budget_tokens: int) -> CompactResult:
        if len(messages) <= self._keep_recent:
            return CompactResult(
                boundary=Message(role="system", content=""),
                preserved=messages,
                tokens_saved=0,
            )

        old = messages[:-self._keep_recent]
        recent = messages[-self._keep_recent:]

        # Replace non-text markers
        cleaned = [self._clean_message(m) for m in old]

        summary = await self._summarize(cleaned)
        boundary = Message(role="system", content=f"[Conversation summary]: {summary}")

        original_tokens = sum(self._estimate_tokens(m) for m in old)
        summary_tokens = self._estimate_tokens(boundary)

        return CompactResult(
            boundary=boundary,
            preserved=recent,
            tokens_saved=max(0, original_tokens - summary_tokens),
        )

    async def summarize(self, messages: list[Message]) -> str:
        """Standalone summarize for WorkingMemory integration."""
        cleaned = [self._clean_message(m) for m in messages]
        return await self._summarize(cleaned)

    async def _summarize(self, messages: list[Message]) -> str:
        conversation = "\n".join(
            f"[{m.role}]: {m.content or '(empty)'}" for m in messages
        )
        prompt_messages = [
            Message(role="system", content=(
                "Summarize the following conversation concisely. "
                "Preserve key decisions, actions taken, and results. "
                "Keep technical details (commands, paths, error messages). "
                "Output a brief summary paragraph."
            )),
            Message(role="user", content=conversation),
        ]
        try:
            response = await self._provider.chat(messages=prompt_messages)
            return response.content or "Unable to summarize."
        except Exception as e:
            return f"Summarization failed: {e}"

    def _clean_message(self, msg: Message) -> Message:
        content = msg.content or ""
        # Replace image/document references with markers
        if "[image" in content.lower() or "base64" in content.lower():
            content = "[image content omitted]"
        if len(content) > 2000:
            content = content[:1500] + "\n...[truncated]..." + content[-300:]
        return Message(role=msg.role, content=content)

    def _estimate_tokens(self, msg: Message) -> int:
        return len(msg.content or "") // 4
