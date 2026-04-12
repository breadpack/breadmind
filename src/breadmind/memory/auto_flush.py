"""Automatic memory flush before context compaction.

Before the conversation context is compacted/compressed, this module
extracts important information (decisions, preferences, findings, TODOs)
and writes them to persistent storage so nothing valuable is lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from breadmind.memory.daily_notes import DailyNotesManager


@dataclass
class FlushableItem:
    """A single piece of information worth preserving."""

    category: str  # "decision", "finding", "todo", "preference"
    content: str
    importance: float = 0.5  # 0.0 – 1.0


class MemoryFlushTarget(Protocol):
    """Protocol for where flushed memories are written."""

    def write(self, items: list[FlushableItem]) -> None: ...


# ------------------------------------------------------------------
# Pattern definitions for extraction
# ------------------------------------------------------------------

_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "decision": [
        re.compile(r"(?:we |I )?decided to\b", re.IGNORECASE),
        re.compile(r"let'?s go with\b", re.IGNORECASE),
        re.compile(r"(?:we |I )?chose to\b", re.IGNORECASE),
        re.compile(r"going (?:to go )?with\b", re.IGNORECASE),
    ],
    "preference": [
        re.compile(r"I prefer\b", re.IGNORECASE),
        re.compile(r"don'?t (?:ever )?do\b", re.IGNORECASE),
        re.compile(r"always use\b", re.IGNORECASE),
        re.compile(r"never use\b", re.IGNORECASE),
    ],
    "finding": [
        re.compile(r"(?:found|discovered) that\b", re.IGNORECASE),
        re.compile(r"turns out\b", re.IGNORECASE),
        re.compile(r"it (?:seems|appears) that\b", re.IGNORECASE),
        re.compile(r"(?:root cause|issue) (?:is|was)\b", re.IGNORECASE),
    ],
    "todo": [
        re.compile(r"\bTODO\b:?", re.IGNORECASE),
        re.compile(r"need to\b", re.IGNORECASE),
        re.compile(r"remember to\b", re.IGNORECASE),
        re.compile(r"don'?t forget to\b", re.IGNORECASE),
    ],
}

# Base importance per category (can be boosted by heuristics)
_BASE_IMPORTANCE: dict[str, float] = {
    "decision": 0.8,
    "preference": 0.7,
    "finding": 0.6,
    "todo": 0.7,
}


class AutoMemoryFlusher:
    """Extracts important information from conversation before compaction.

    Integrates with the *PreCompact* lifecycle event.
    """

    def __init__(
        self,
        targets: list[MemoryFlushTarget] | None = None,
        importance_threshold: float = 0.6,
    ) -> None:
        self._targets: list[MemoryFlushTarget] = targets or []
        self._threshold = importance_threshold

    def extract_flushable(self, messages: list[dict]) -> list[FlushableItem]:
        """Scan conversation messages for important items to preserve.

        Looks for:
        - Explicit decisions ("we decided to...", "let's go with...")
        - User preferences ("I prefer...", "don't do...")
        - Important findings ("found that...", "discovered...")
        - Action items ("TODO:", "need to...", "remember to...")
        """
        items: list[FlushableItem] = []
        seen_contents: set[str] = set()

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content.strip():
                continue

            # Check each sentence-like fragment
            for sentence in re.split(r"[.!?\n]+", content):
                sentence = sentence.strip()
                if len(sentence) < 10:
                    continue

                category, importance = self._classify_importance(sentence)
                if category is None:
                    continue
                if importance < self._threshold:
                    continue

                # Deduplicate
                key = sentence.lower().strip()
                if key in seen_contents:
                    continue
                seen_contents.add(key)

                items.append(
                    FlushableItem(
                        category=category,
                        content=sentence,
                        importance=importance,
                    )
                )

        return items

    def flush(self, messages: list[dict]) -> list[FlushableItem]:
        """Extract and write flushable items to all targets.

        Returns what was flushed.
        """
        items = self.extract_flushable(messages)
        if items:
            for target in self._targets:
                target.write(items)
        return items

    def _classify_importance(self, text: str) -> tuple[str | None, float]:
        """Classify a text snippet into category and importance score.

        Returns ``(None, 0.0)`` when no pattern matches.
        """
        for category, patterns in _PATTERNS.items():
            for pattern in patterns:
                if pattern.search(text):
                    importance = _BASE_IMPORTANCE[category]
                    # Boost for emphasis markers
                    if any(m in text for m in ("!", "IMPORTANT", "CRITICAL")):
                        importance = min(importance + 0.15, 1.0)
                    return category, importance

        return None, 0.0


class DailyNoteFlushTarget:
    """Writes flushed memories to today's daily note."""

    def __init__(self, daily_notes_manager: DailyNotesManager) -> None:
        self._dnm = daily_notes_manager

    def write(self, items: list[FlushableItem]) -> None:
        if not items:
            return

        lines = ["## Auto-flushed Memories\n"]
        for item in items:
            lines.append(
                f"- **[{item.category}]** (importance: {item.importance:.1f}) "
                f"{item.content}"
            )
        text = "\n".join(lines)
        self._dnm.append_today(text)
