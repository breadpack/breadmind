"""PatternDetector tests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest


@pytest.fixture
def weekly_tasks():
    from breadmind.personal.models import Task
    now = datetime.now(timezone.utc)
    return [
        Task(id=f"t{i}", title="주간 보고서 작성", status="done",
             created_at=now - timedelta(weeks=i))
        for i in range(5)
    ]


@pytest.fixture
def mock_registry(weekly_tasks):
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()
    adapter = AsyncMock()
    adapter.domain = "task"
    adapter.source = "builtin"
    adapter.list_items = AsyncMock(return_value=weekly_tasks)
    registry.register(adapter)
    return registry


@pytest.mark.asyncio
async def test_detect_weekly_pattern(mock_registry):
    from breadmind.personal.pattern_detector import PatternDetector
    detector = PatternDetector(mock_registry, min_occurrences=3)
    patterns = await detector.detect_recurring_tasks("alice")
    assert len(patterns) >= 1
    assert patterns[0].frequency == "weekly"
    assert "주간 보고서" in patterns[0].title


@pytest.mark.asyncio
async def test_no_pattern_with_few_tasks():
    from breadmind.personal.pattern_detector import PatternDetector
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.personal.models import Task

    registry = AdapterRegistry()
    adapter = AsyncMock()
    adapter.domain = "task"
    adapter.source = "builtin"
    adapter.list_items = AsyncMock(return_value=[
        Task(id="t1", title="Random task", status="done")
    ])
    registry.register(adapter)

    detector = PatternDetector(registry, min_occurrences=3)
    patterns = await detector.detect_recurring_tasks("alice")
    assert patterns == []


@pytest.mark.asyncio
async def test_suggestions(mock_registry):
    from breadmind.personal.pattern_detector import PatternDetector
    detector = PatternDetector(mock_registry, min_occurrences=3)
    suggestions = await detector.get_suggestions("alice")
    assert len(suggestions) >= 1
    assert "반복" in suggestions[0]


def test_normalize_title():
    from breadmind.personal.pattern_detector import PatternDetector
    detector = PatternDetector(None)
    assert detector._normalize_title("주간 보고서 2026-03-17") == "주간 보고서"
    assert detector._normalize_title("Sprint #42 Review") == "sprint  review"


def test_detect_daily_frequency():
    from breadmind.personal.pattern_detector import PatternDetector
    from breadmind.personal.models import Task
    now = datetime.now(timezone.utc)
    tasks = [
        Task(id=f"t{i}", title="Daily standup", status="done",
             created_at=now - timedelta(days=i))
        for i in range(5)
    ]
    detector = PatternDetector(None, min_occurrences=3)
    freq = detector._detect_frequency(tasks)
    assert freq == "daily"
