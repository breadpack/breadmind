"""Reflexion pattern — learn from task failures via self-reflection."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, LLMProvider

if TYPE_CHECKING:
    from breadmind.memory.episodic import EpisodicMemory

logger = logging.getLogger(__name__)

_REFLECT_PROMPT = (
    "A task just failed. Analyze what went wrong and write a concise lesson "
    "(1-3 sentences) that would help avoid this failure in the future.\n\n"
    "Task: {task}\n"
    "Error: {error}\n"
    "Context: {context}\n\n"
    "Write ONLY the lesson, no preamble."
)

_RECALL_PROMPT = (
    "Check if any of these past lessons are relevant to the current task.\n\n"
    "Current task: {task}\n\n"
    "Past lessons:\n{lessons}\n\n"
    "Return ONLY the relevant lessons (copy them exactly), one per line. "
    "If none are relevant, return NONE."
)


class ReflexionEngine:
    """Learn from failures and inject lessons into future tasks."""

    def __init__(
        self,
        provider: LLMProvider,
        episodic_memory: EpisodicMemory,
    ):
        self._provider = provider
        self._episodic = episodic_memory

    async def reflect_on_failure(
        self,
        task_description: str,
        error_message: str,
        context: str = "",
    ) -> str | None:
        """Generate and store a lesson from a failed task."""
        prompt = _REFLECT_PROMPT.format(
            task=task_description,
            error=error_message[:500],
            context=context[:500],
        )
        try:
            resp = await self._provider.chat([
                LLMMessage(role="user", content=prompt),
            ])
            lesson = (resp.content or "").strip()
            if not lesson or len(lesson) < 10:
                return None

            # Store lesson in episodic memory
            await self._episodic.add_note(
                content=f"[Lesson] {lesson}",
                keywords=self._extract_keywords(task_description),
                tags=["reflexion", "lesson"],
                context_description=f"Failure reflection: {task_description[:100]}",
            )
            logger.info(f"Reflexion lesson stored: {lesson[:100]}")
            return lesson
        except Exception:
            logger.exception("Reflexion failed")
            return None

    async def recall_lessons(
        self, task_description: str, limit: int = 5,
    ) -> list[str]:
        """Retrieve relevant past lessons for a task."""
        keywords = self._extract_keywords(task_description)
        if not keywords:
            return []

        notes = await self._episodic.search_by_tags(["reflexion"], limit=limit * 2)
        if not notes:
            return []

        # Filter by keyword relevance
        keyword_set = set(k.lower() for k in keywords)
        scored = []
        for note in notes:
            note_keywords = set(k.lower() for k in (note.keywords or []))
            overlap = len(keyword_set & note_keywords)
            if overlap > 0:
                scored.append((overlap * note.decay_weight, note.content))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [content for _, content in scored[:limit]]

    async def store_success(
        self, task_description: str, result_summary: str,
    ) -> None:
        """Store a successful task trajectory for future reference."""
        await self._episodic.add_note(
            content=f"[Success] Task: {task_description}\nResult: {result_summary[:300]}",
            keywords=self._extract_keywords(task_description),
            tags=["reflexion", "success_trajectory"],
            context_description=f"Successful task: {task_description[:100]}",
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        import re
        words = re.findall(r"[a-zA-Z0-9._-]+", text.lower())
        stopwords = {"the", "a", "an", "is", "are", "to", "of", "in", "for", "and", "or", "it", "this"}
        return [w for w in words if len(w) > 2 and w not in stopwords][:10]
