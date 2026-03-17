"""Pattern detection for recurring task/event suggestions."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DetectedPattern:
    """A detected recurring pattern."""
    pattern_type: str  # "weekly_task", "daily_task", "recurring_event"
    title: str
    frequency: str  # "daily", "weekly", "monthly"
    confidence: float  # 0.0-1.0
    occurrences: int
    suggestion: str  # Human-readable suggestion


class PatternDetector:
    """Detects recurring patterns in task/event creation."""

    def __init__(self, adapter_registry: Any, min_occurrences: int = 3) -> None:
        self._registry = adapter_registry
        self._min_occurrences = min_occurrences

    async def detect_recurring_tasks(self, user_id: str) -> list[DetectedPattern]:
        """Analyze completed tasks for recurring title patterns."""
        try:
            adapter = self._registry.get_adapter("task", "builtin")
        except KeyError:
            return []

        # Get completed tasks from last 30 days
        tasks = await adapter.list_items(
            filters={"user_id": user_id, "status": "done"},
            limit=200,
        )

        if len(tasks) < self._min_occurrences:
            return []

        # Group by normalized title
        title_groups: dict[str, list] = defaultdict(list)
        for task in tasks:
            normalized = self._normalize_title(task.title)
            title_groups[normalized].append(task)

        patterns = []
        for title, group in title_groups.items():
            if len(group) < self._min_occurrences:
                continue

            frequency = self._detect_frequency(group)
            if frequency:
                confidence = min(len(group) / (self._min_occurrences * 2), 1.0)
                original_title = group[0].title
                patterns.append(DetectedPattern(
                    pattern_type=f"{frequency}_task",
                    title=original_title,
                    frequency=frequency,
                    confidence=confidence,
                    occurrences=len(group),
                    suggestion=(
                        f"'{original_title}'을(를) "
                        f"{self._frequency_kr(frequency)} 반복 할 일로 "
                        f"설정하시겠습니까?"
                    ),
                ))

        # Sort by confidence descending
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns

    async def get_suggestions(self, user_id: str) -> list[str]:
        """Get human-readable automation suggestions."""
        patterns = await self.detect_recurring_tasks(user_id)
        return [p.suggestion for p in patterns]

    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison (lowercase, strip numbers/dates)."""
        # Remove dates, numbers, leading/trailing whitespace
        normalized = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}', '', title)
        normalized = re.sub(r'\d+[월일주차회]', '', normalized)
        normalized = re.sub(r'#\d+', '', normalized)
        return normalized.strip().lower()

    def _detect_frequency(self, tasks: list) -> str | None:
        """Detect frequency from task creation timestamps."""
        if len(tasks) < self._min_occurrences:
            return None

        # Sort by created_at
        sorted_tasks = sorted(tasks, key=lambda t: t.created_at)
        intervals = []
        for i in range(1, len(sorted_tasks)):
            delta = (
                sorted_tasks[i].created_at - sorted_tasks[i - 1].created_at
            ).total_seconds() / 3600
            intervals.append(delta)

        if not intervals:
            return None

        avg_hours = sum(intervals) / len(intervals)

        # Classify frequency
        if 18 <= avg_hours <= 30:  # ~daily
            return "daily"
        elif 144 <= avg_hours <= 192:  # ~weekly (6-8 days)
            return "weekly"
        elif 672 <= avg_hours <= 768:  # ~monthly (28-32 days)
            return "monthly"
        return None

    @staticmethod
    def _frequency_kr(frequency: str) -> str:
        return {"daily": "매일", "weekly": "매주", "monthly": "매월"}.get(
            frequency, frequency
        )
