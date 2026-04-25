"""Reflexion pattern — learn from task failures via self-reflection."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, LLMProvider

if TYPE_CHECKING:
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.episodic_recorder import EpisodicRecorder
    from breadmind.memory.signals import SignalDetector

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
    """Learn from failures and inject lessons into future tasks.

    The optional ``signal_detector`` / ``episodic_recorder`` kwargs let the
    engine emit a :class:`SignalKind.REFLEXION` event into the episodic
    pipeline whenever a lesson is recorded. Both default to ``None`` so the
    engine remains a safe no-op for callers that only want LLM reflection.
    """

    def __init__(
        self,
        provider: LLMProvider,
        episodic_memory: EpisodicMemory,
        *,
        signal_detector: SignalDetector | None = None,
        episodic_recorder: EpisodicRecorder | None = None,
    ):
        self._provider = provider
        self._episodic = episodic_memory
        self._signal_detector = signal_detector
        self._episodic_recorder = episodic_recorder

    async def reflect_on_failure(
        self,
        task_description: str,
        error_message: str,
        context: str = "",
        *,
        user_id: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> str | None:
        """Generate and store a lesson from a failed task.

        When the LLM produces a usable lesson, this delegates to
        :meth:`record_lesson` so the REFLEXION signal pipeline runs uniformly
        regardless of who (LLM vs. caller) authored the lesson text.
        """
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

            await self.record_lesson(
                lesson,
                user_id=user_id,
                session_id=session_id,
                task_description=task_description,
            )
            logger.info(f"Reflexion lesson stored: {lesson[:100]}")
            return lesson
        except Exception:
            logger.exception("Reflexion failed")
            return None

    async def record_lesson(
        self,
        lesson_text: str,
        *,
        user_id: str | None = None,
        session_id: uuid.UUID | None = None,
        task_description: str | None = None,
    ) -> None:
        """Persist a lesson into episodic memory and emit a REFLEXION signal.

        The lesson is always written through ``EpisodicMemory.add_note``.
        Additionally, when both ``signal_detector`` and ``episodic_recorder``
        are wired, a :class:`SignalKind.REFLEXION` event is dispatched
        fire-and-forget — recorder failures are absorbed in ``_safe_record``
        so they never bubble back into the caller's path.
        """
        text = (lesson_text or "").strip()
        if not text:
            return

        keywords = self._extract_keywords(task_description or text)
        ctx_desc = (
            f"Failure reflection: {task_description[:100]}"
            if task_description
            else "Reflexion lesson"
        )
        try:
            await self._episodic.add_note(
                content=f"[Lesson] {text}",
                keywords=keywords,
                tags=["reflexion", "lesson"],
                context_description=ctx_desc,
            )
        except Exception:
            logger.warning("Reflexion episodic add_note failed", exc_info=True)

        self._emit_reflexion_signal(text, user_id=user_id, session_id=session_id)

    def _emit_reflexion_signal(
        self,
        lesson_text: str,
        *,
        user_id: str | None,
        session_id: uuid.UUID | None,
    ) -> None:
        """Build a REFLEXION SignalEvent and hand it to the recorder.

        No-op when either ``signal_detector`` or ``episodic_recorder`` is
        unset. Mirrors the fire-and-forget pattern used by
        ``CoreAgent._emit_user_signal`` and ``ToolExecutor._emit_tool_signal``
        so recorder errors are isolated from the calling path.
        """
        if self._signal_detector is None or self._episodic_recorder is None:
            return
        try:
            from breadmind.memory.signals import TurnSnapshot

            snap = TurnSnapshot(
                user_id=user_id or "",
                session_id=session_id,
                user_message=lesson_text,
                last_tool_name=None,
                prior_turn_summary=None,
            )
            evt = self._signal_detector.on_reflexion(
                snap, reflexion_text=lesson_text,
            )
            recorder = self._episodic_recorder

            async def _safe_record():
                try:
                    await recorder.record(evt)
                except Exception:
                    logger.debug("episodic recorder failed", exc_info=True)

            try:
                asyncio.create_task(_safe_record())
            except RuntimeError:
                # No running loop (sync context) — drop silently.
                logger.debug(
                    "could not schedule reflexion recorder task", exc_info=True,
                )
        except Exception:
            logger.warning(
                "ReflexionEngine _emit_reflexion_signal swallowed", exc_info=True,
            )

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
