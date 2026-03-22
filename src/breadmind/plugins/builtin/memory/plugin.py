"""Memory plugin — long-term memory tools: save, search, delete."""

from __future__ import annotations

import logging
from typing import Any

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger("breadmind.plugins.memory")


class MemoryPlugin(BaseToolPlugin):
    """Provides memory_save, memory_search, and memory_delete tools."""

    name = "memory"
    version = "0.1.0"

    def __init__(self) -> None:
        self._episodic_memory: Any = None
        self._profiler: Any = None
        self._smart_retriever: Any = None

    async def setup(self, container: Any) -> None:
        self._episodic_memory = container.get("episodic_memory")
        self._profiler = container.get_optional("profiler")
        self._smart_retriever = container.get_optional("smart_retriever")

    def get_tools(self) -> list:
        return [self.memory_save, self.memory_search, self.memory_delete]

    @tool(description="Save important information for future conversations. Use when the user asks to remember something, states a preference, or shares a fact worth keeping. category: 'preference', 'fact', 'instruction', or 'incident'.")
    async def memory_save(self, content: str, category: str = "fact") -> str:
        if self._episodic_memory is None:
            return "Memory system not available."
        try:
            valid_categories = {"preference", "fact", "instruction", "incident"}
            if category not in valid_categories:
                category = "fact"

            # Store as episodic note with structured tags
            keywords = content.lower().split()[:10]  # Simple keyword extraction
            note = await self._episodic_memory.add_note(
                content=content,
                keywords=keywords,
                tags=[f"memory:{category}", "explicit_memory"],
                context_description=f"User-requested memory ({category})",
            )
            # Pin explicit user memories — they should never decay
            self._episodic_memory.pin_note(note)

            # Also store as user preference if applicable
            if category == "preference" and self._profiler:
                from breadmind.memory.profiler import UserPreference
                await self._profiler.add_preference("default", UserPreference(
                    category=content[:50], description=content,
                ))

            # Index in SmartRetriever if available
            if self._smart_retriever:
                try:
                    await self._smart_retriever.index_task_result(
                        role="user", task_desc=f"memory_{category}",
                        result_summary=content, success=True,
                    )
                except Exception:
                    pass

            return f"Remembered: {content[:100]}{'...' if len(content) > 100 else ''}"
        except Exception as e:
            return f"Failed to save memory: {e}"

    @tool(description="Search your long-term memory for previously saved information. Use at conversation start or when context from past interactions would be helpful.")
    async def memory_search(self, query: str, limit: int = 5) -> str:
        if self._episodic_memory is None:
            return "Memory system not available."
        try:
            results = []

            # Try smart retriever first (vector + KG)
            if self._smart_retriever:
                try:
                    context_items = await self._smart_retriever.retrieve_context(
                        query, token_budget=1500, limit=limit,
                    )
                    for item in context_items:
                        results.append(f"- [{item.source}] {item.content}")
                except Exception:
                    pass

            # Fallback to keyword search
            if not results:
                keywords = query.lower().split()[:5]
                notes = await self._episodic_memory.search_by_keywords(
                    keywords, limit=limit,
                )
                for note in notes:
                    results.append(f"- {note.content}")

            if not results:
                return "No relevant memories found."
            return "Memories found:\n" + "\n".join(results)
        except Exception as e:
            return f"Memory search failed: {e}"

    @tool(description="Delete a previously saved memory by its content. Use when the user asks to forget something or when information is outdated.")
    async def memory_delete(self, content_match: str) -> str:
        if self._episodic_memory is None:
            return "Memory system not available."
        try:
            # Search for matching notes
            keywords = content_match.lower().split()[:5]
            notes = await self._episodic_memory.search_by_keywords(
                keywords, limit=5,
            )

            deleted = 0
            for note in notes:
                if content_match.lower() in note.content.lower():
                    await self._episodic_memory.delete_note(note.id)
                    deleted += 1

            if deleted == 0:
                return f"No matching memories found for: {content_match}"
            return f"Deleted {deleted} memory/memories matching: {content_match[:50]}"
        except Exception as e:
            return f"Failed to delete memory: {e}"
