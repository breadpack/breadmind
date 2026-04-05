"""Tests for the daily notes memory system."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from breadmind.memory.daily_notes import DailyNote, DailyNotesManager


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "daily_notes"
    d.mkdir()
    return d


@pytest.fixture
def manager(notes_dir: Path) -> DailyNotesManager:
    return DailyNotesManager(notes_dir)


class TestDailyNote:
    def test_append_writes_to_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        path.write_text("initial\n", encoding="utf-8")
        note = DailyNote(date=date.today(), content="initial\n", file_path=path)

        note.append("added line\n")

        assert note.content == "initial\nadded line\n"
        assert path.read_text(encoding="utf-8") == "initial\nadded line\n"


class TestDailyNotesManager:
    def test_get_today_creates_file(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        note = manager.get_today()

        assert note.date == date.today()
        assert note.file_path.exists()
        assert date.today().isoformat() in note.content

    def test_get_today_returns_existing(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        # Create the file first
        note1 = manager.get_today()
        note1.append("extra stuff")

        # Should read existing content
        note2 = manager.get_today()
        assert "extra stuff" in note2.content

    def test_get_note_returns_none_for_missing(self, manager: DailyNotesManager) -> None:
        result = manager.get_note(date(2000, 1, 1))
        assert result is None

    def test_get_note_returns_existing(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        d = date(2025, 6, 15)
        path = notes_dir / "2025-06-15.md"
        path.write_text("hello", encoding="utf-8")

        note = manager.get_note(d)
        assert note is not None
        assert note.content == "hello"
        assert note.date == d

    def test_get_recent_returns_today_and_yesterday(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        today = date.today()
        yesterday = today - timedelta(days=1)

        (notes_dir / f"{today.isoformat()}.md").write_text("today", encoding="utf-8")
        (notes_dir / f"{yesterday.isoformat()}.md").write_text("yesterday", encoding="utf-8")

        recent = manager.get_recent(days=2)
        assert len(recent) == 2
        assert recent[0].date == today
        assert recent[1].date == yesterday

    def test_get_recent_skips_missing_days(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        today = date.today()
        (notes_dir / f"{today.isoformat()}.md").write_text("today", encoding="utf-8")

        recent = manager.get_recent(days=5)
        assert len(recent) == 1

    def test_append_today_adds_timestamp(self, manager: DailyNotesManager) -> None:
        manager.append_today("test message")

        note = manager.get_today()
        assert "test message" in note.content
        assert "UTC" in note.content

    def test_search_finds_matching_lines(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        today = date.today()
        content = "line one\nkubernetes deploy\nline three\n"
        (notes_dir / f"{today.isoformat()}.md").write_text(content, encoding="utf-8")

        results = manager.search("kubernetes")
        assert len(results) == 1
        note, lines = results[0]
        assert note.date == today
        assert any("kubernetes" in l.lower() for l in lines)

    def test_search_case_insensitive(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        today = date.today()
        (notes_dir / f"{today.isoformat()}.md").write_text("Found BUG here\n", encoding="utf-8")

        results = manager.search("bug")
        assert len(results) == 1

    def test_get_context_for_session(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        today = date.today()
        (notes_dir / f"{today.isoformat()}.md").write_text("today note", encoding="utf-8")

        ctx = manager.get_context_for_session()
        assert "Recent Daily Notes" in ctx
        assert "today note" in ctx

    def test_get_context_for_session_empty(self, manager: DailyNotesManager) -> None:
        ctx = manager.get_context_for_session()
        assert ctx == ""

    def test_cleanup_removes_old_files(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        old_date = date.today() - timedelta(days=100)
        recent_date = date.today() - timedelta(days=10)

        (notes_dir / f"{old_date.isoformat()}.md").write_text("old", encoding="utf-8")
        (notes_dir / f"{recent_date.isoformat()}.md").write_text("recent", encoding="utf-8")

        removed = manager.cleanup(keep_days=90)

        assert removed == 1
        assert not (notes_dir / f"{old_date.isoformat()}.md").exists()
        assert (notes_dir / f"{recent_date.isoformat()}.md").exists()

    def test_cleanup_ignores_non_date_files(self, manager: DailyNotesManager, notes_dir: Path) -> None:
        (notes_dir / "readme.md").write_text("not a note", encoding="utf-8")

        removed = manager.cleanup(keep_days=0)
        assert removed == 0
        assert (notes_dir / "readme.md").exists()

    def test_constructor_creates_base_dir(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "deep" / "nested" / "notes"
        mgr = DailyNotesManager(new_dir)
        assert new_dir.is_dir()
