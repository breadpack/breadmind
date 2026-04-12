"""Daily notes memory system.

OpenClaw-inspired daily notes: each day gets a running context file
stored as ``memory/YYYY-MM-DD.md``.  Today's and yesterday's notes are
auto-loaded at session start so the agent always has recent context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


@dataclass
class DailyNote:
    """A single day's note file."""

    date: date
    content: str
    file_path: Path

    def append(self, text: str) -> None:
        """Append *text* to the daily note (both in-memory and on disk)."""
        self.content += text
        with self.file_path.open("a", encoding="utf-8") as f:
            f.write(text)


class DailyNotesManager:
    """Manages daily context notes in ``<base_dir>/YYYY-MM-DD.md`` format.

    Today's and yesterday's notes are auto-loaded at session start.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_today(self) -> DailyNote:
        """Get or create today's note."""
        today = date.today()
        path = self._note_path(today)
        if path.exists():
            content = path.read_text(encoding="utf-8")
        else:
            content = f"# Daily Note — {today.isoformat()}\n\n"
            path.write_text(content, encoding="utf-8")
        return DailyNote(date=today, content=content, file_path=path)

    def get_note(self, d: date) -> DailyNote | None:
        """Get note for a specific date, or ``None`` if not found."""
        path = self._note_path(d)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        return DailyNote(date=d, content=content, file_path=path)

    def get_recent(self, days: int = 2) -> list[DailyNote]:
        """Get recent notes (default: today + yesterday)."""
        notes: list[DailyNote] = []
        today = date.today()
        for offset in range(days):
            d = today - timedelta(days=offset)
            note = self.get_note(d)
            if note is not None:
                notes.append(note)
        return notes

    def append_today(self, text: str) -> None:
        """Append *text* to today's note with a timestamp prefix."""
        note = self.get_today()
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        note.append(f"\n[{now}] {text}\n")

    def search(
        self, query: str, max_days: int = 30
    ) -> list[tuple[DailyNote, list[str]]]:
        """Simple text search across recent daily notes.

        Returns ``(note, matching_lines)`` tuples.
        """
        results: list[tuple[DailyNote, list[str]]] = []
        query_lower = query.lower()
        today = date.today()

        for offset in range(max_days):
            d = today - timedelta(days=offset)
            note = self.get_note(d)
            if note is None:
                continue
            matching = [
                line
                for line in note.content.splitlines()
                if query_lower in line.lower()
            ]
            if matching:
                results.append((note, matching))

        return results

    def get_context_for_session(self) -> str:
        """Return formatted context string from recent notes for session injection."""
        notes = self.get_recent(days=2)
        if not notes:
            return ""

        parts: list[str] = ["## Recent Daily Notes\n"]
        for note in notes:
            parts.append(f"### {note.date.isoformat()}\n{note.content}\n")
        return "\n".join(parts)

    def cleanup(self, keep_days: int = 90) -> int:
        """Remove notes older than *keep_days*. Returns count of removed files."""
        cutoff = date.today() - timedelta(days=keep_days)
        removed = 0

        for path in self._base_dir.glob("*.md"):
            try:
                file_date = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink()
                removed += 1

        return removed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _note_path(self, d: date) -> Path:
        return self._base_dir / f"{d.isoformat()}.md"
