"""Flicker-free alternate-screen rendering.

Enabled via ``BREADMIND_NO_FLICKER=1`` environment variable.
Uses ANSI escape sequences for alternate screen buffer and cursor
control, with virtual scrollback for reviewing past output.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, TextIO


@dataclass
class ScreenState:
    lines: list[str] = field(default_factory=list)
    cursor_row: int = 0
    cursor_col: int = 0


class AltScreenRenderer:
    """Flicker-free rendering using alternate screen buffer.

    Enabled via ``BREADMIND_NO_FLICKER=1`` env var.
    Uses ANSI escape sequences for alt screen and cursor control.
    Provides virtual scrollback for reviewing past output.
    """

    ENTER_ALT = "\033[?1049h"
    EXIT_ALT = "\033[?1049l"
    CLEAR_LINE = "\033[2K"
    CURSOR_HOME = "\033[H"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._active = False
        self._scrollback: list[str] = []
        self._viewport_height: int = 24
        self._viewport_offset: int = 0
        self._last_frame: list[str] = []

    @staticmethod
    def is_enabled() -> bool:
        return os.environ.get("BREADMIND_NO_FLICKER", "0") == "1"

    @property
    def active(self) -> bool:
        return self._active

    @property
    def scrollback(self) -> list[str]:
        return list(self._scrollback)

    @property
    def viewport_offset(self) -> int:
        return self._viewport_offset

    @contextmanager
    def alt_screen(self) -> Iterator[AltScreenRenderer]:
        """Context manager for alt screen mode."""
        self.enter()
        try:
            yield self
        finally:
            self.exit()

    def enter(self) -> None:
        """Enter alternate screen buffer."""
        if self._active:
            return
        self._stream.write(self.ENTER_ALT)
        self._stream.write(self.HIDE_CURSOR)
        self._stream.flush()
        self._active = True
        self._last_frame = []

    def exit(self) -> None:
        """Exit alternate screen buffer and restore terminal."""
        if not self._active:
            return
        self._stream.write(self.SHOW_CURSOR)
        self._stream.write(self.EXIT_ALT)
        self._stream.flush()
        self._active = False
        self._last_frame = []

    def render_frame(self, lines: list[str]) -> None:
        """Render a frame to the alt screen without flicker.

        Only redraws lines that have changed since the previous frame.
        """
        if not self._active:
            return

        for i in range(self._viewport_height):
            new_line = lines[i] if i < len(lines) else ""
            old_line = self._last_frame[i] if i < len(self._last_frame) else ""
            if new_line != old_line:
                # Move cursor to row i+1, col 1  (1-indexed)
                self._stream.write(f"\033[{i + 1};1H")
                self._stream.write(self.CLEAR_LINE)
                self._stream.write(new_line)

        self._stream.flush()
        self._last_frame = list(lines[: self._viewport_height])

    def append_scrollback(self, text: str) -> None:
        """Append text to the virtual scrollback buffer."""
        self._scrollback.extend(text.splitlines())

    def scroll_up(self, n: int = 1) -> None:
        """Scroll viewport up (towards older content)."""
        max_offset = max(0, len(self._scrollback) - self._viewport_height)
        self._viewport_offset = min(self._viewport_offset + n, max_offset)

    def scroll_down(self, n: int = 1) -> None:
        """Scroll viewport down (towards newer content)."""
        self._viewport_offset = max(self._viewport_offset - n, 0)

    def get_visible_lines(self) -> list[str]:
        """Return the lines currently visible in the viewport."""
        start = max(0, len(self._scrollback) - self._viewport_height - self._viewport_offset)
        end = start + self._viewport_height
        return self._scrollback[start:end]
