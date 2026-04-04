"""v2 ContextBuilder: 메모리 검색 결과를 PromptBlock으로 패키징."""
from __future__ import annotations
from typing import Any
from breadmind.core.protocols import PromptBlock
from breadmind.plugins.v2_builtin.memory.smart_retriever import SmartRetriever


class ContextBuilder:
    """검색 결과를 PromptBlock으로 변환. MemoryProtocol.build_context_block() 구현."""

    def __init__(self, retriever: SmartRetriever, token_counter: Any = None) -> None:
        self._retriever = retriever
        self._count_tokens = token_counter or (lambda text: len(text) // 4)

    async def build_context_block(
        self, session_id: str, query: str, budget_tokens: int,
    ) -> PromptBlock:
        results = await self._retriever.retrieve(query, limit=10)

        if not results:
            return PromptBlock(
                section="memory_context",
                content="",
                cacheable=False,
                priority=4,
            )

        # Fit results within budget
        content_parts = []
        tokens_used = 0
        for item in results:
            item_tokens = self._count_tokens(item)
            if tokens_used + item_tokens > budget_tokens:
                break
            content_parts.append(item)
            tokens_used += item_tokens

        content = "Relevant context from memory:\n" + "\n".join(content_parts)

        return PromptBlock(
            section="memory_context",
            content=content,
            cacheable=False,
            priority=4,
        )
