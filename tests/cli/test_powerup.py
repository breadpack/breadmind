"""Tests for Interactive Lessons (/powerup)."""

from __future__ import annotations

from breadmind.cli.powerup import LessonStep, PowerUpManager


class TestPowerUpManager:
    def test_init_has_lessons(self):
        mgr = PowerUpManager()
        lessons = mgr.list_lessons()
        assert len(lessons) >= 4

    def test_list_lessons_by_category(self):
        mgr = PowerUpManager()
        basics = mgr.list_lessons(category="basics")
        assert all(l.category == "basics" for l in basics)
        assert len(basics) >= 1

    def test_get_lesson_by_id(self):
        mgr = PowerUpManager()
        lesson = mgr.get_lesson("basics-chat")
        assert lesson is not None
        assert lesson.title == "Your First Conversation"

    def test_get_lesson_nonexistent(self):
        mgr = PowerUpManager()
        assert mgr.get_lesson("nonexistent") is None

    def test_mark_complete_and_progress(self):
        mgr = PowerUpManager()
        progress = mgr.get_progress()
        assert progress["completed"] == 0
        mgr.mark_complete("basics-chat")
        progress = mgr.get_progress()
        assert progress["completed"] == 1
        assert progress["remaining"] == progress["total"] - 1

    def test_get_next_recommended(self):
        mgr = PowerUpManager()
        first = mgr.get_next_recommended()
        assert first is not None
        assert first.id == "basics-chat"
        mgr.mark_complete("basics-chat")
        second = mgr.get_next_recommended()
        assert second is not None
        assert second.id != "basics-chat"

    def test_all_completed_returns_none(self):
        mgr = PowerUpManager()
        for lesson in mgr.list_lessons():
            mgr.mark_complete(lesson.id)
        assert mgr.get_next_recommended() is None

    def test_render_step(self):
        mgr = PowerUpManager()
        step = LessonStep(
            title="Test Step",
            description="A test description",
            demo_command="breadmind test",
            expected_output="Success",
        )
        rendered = mgr.render_step(step)
        assert "## Test Step" in rendered
        assert "A test description" in rendered
        assert "$ breadmind test" in rendered
        assert "Expected: Success" in rendered

    def test_progress_percent(self):
        mgr = PowerUpManager()
        total = mgr.get_progress()["total"]
        mgr.mark_complete("basics-chat")
        progress = mgr.get_progress()
        expected_pct = round(1 / total * 100, 1)
        assert progress["percent"] == expected_pct
