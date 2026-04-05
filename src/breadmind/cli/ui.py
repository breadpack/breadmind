"""Rich-based CLI UI utilities with plain-text fallback."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator

if TYPE_CHECKING:
    pass

_RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.markdown import Markdown as RichMarkdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:
    pass


class ConsoleUI:
    """Unified console output with rich rendering and plain-text fallback."""

    def __init__(self, *, force_plain: bool = False) -> None:
        self._rich = _RICH_AVAILABLE and not force_plain
        if self._rich:
            self._console = Console()
        else:
            self._console = None  # type: ignore[assignment]

    @property
    def is_rich(self) -> bool:
        """Whether rich rendering is active."""
        return self._rich

    # -- message helpers -------------------------------------------------- #

    def info(self, msg: str) -> None:
        """Print an informational message (blue/cyan)."""
        if self._rich:
            self._console.print(f"[cyan][i][/cyan] {msg}")
        else:
            print(f"[i] {msg}")

    def success(self, msg: str) -> None:
        """Print a success message (green)."""
        if self._rich:
            self._console.print(f"[green][ok][/green] {msg}")
        else:
            print(f"[ok] {msg}")

    def warning(self, msg: str) -> None:
        """Print a warning message (yellow)."""
        if self._rich:
            self._console.print(f"[yellow][!][/yellow] {msg}")
        else:
            print(f"[!] {msg}")

    def error(self, msg: str) -> None:
        """Print an error message (red)."""
        if self._rich:
            self._console.print(f"[red][x][/red] {msg}")
        else:
            print(f"[x] {msg}")

    # -- spinner ---------------------------------------------------------- #

    @contextmanager
    def spinner(self, msg: str) -> Generator[None, None, None]:
        """Context manager that shows a loading spinner while work runs.

        Falls back to simple start/done messages without rich.
        """
        if self._rich:
            from rich.status import Status

            with self._console.status(msg):
                yield
        else:
            print(f"  {msg}...", end=" ", flush=True)
            yield
            print("done")

    # -- structured output ------------------------------------------------ #

    def panel(self, title: str, content: str) -> None:
        """Display content inside a bordered panel."""
        if self._rich:
            self._console.print(Panel(content, title=title))
        else:
            width = max(len(title) + 4, 50)
            border = "=" * width
            print(border)
            print(f"  {title}")
            print("-" * width)
            print(f"  {content}")
            print(border)

    def table(self, headers: list[str], rows: list[list[Any]]) -> None:
        """Display data as a table."""
        if self._rich:
            tbl = Table()
            for h in headers:
                tbl.add_column(h)
            for row in rows:
                tbl.add_row(*(str(c) for c in row))
            self._console.print(tbl)
        else:
            # Simple column-aligned output
            col_widths = [len(h) for h in headers]
            for row in rows:
                for i, cell in enumerate(row):
                    if i < len(col_widths):
                        col_widths[i] = max(col_widths[i], len(str(cell)))

            header_line = "  ".join(
                h.ljust(col_widths[i]) for i, h in enumerate(headers)
            )
            print(header_line)
            print("-" * len(header_line))
            for row in rows:
                print(
                    "  ".join(
                        str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)
                    )
                )

    def markdown(self, text: str) -> None:
        """Render Markdown text."""
        if self._rich:
            self._console.print(RichMarkdown(text))
        else:
            print(text)

    # -- input helpers ---------------------------------------------------- #

    def prompt(self, msg: str, *, default: str | None = None) -> str:
        """Prompt the user for input with an optional default value."""
        suffix = f" [{default}]" if default else ""
        if self._rich:
            text = self._console.input(f"[bold cyan]{msg}{suffix}:[/bold cyan] ")
        else:
            text = input(f"{msg}{suffix}: ")
        if not text and default is not None:
            return default
        return text

    def confirm(self, msg: str) -> bool:
        """Ask a yes/no question and return the boolean result."""
        if self._rich:
            answer = self._console.input(f"[bold yellow]{msg} (y/n):[/bold yellow] ")
        else:
            answer = input(f"{msg} (y/n): ")
        return answer.strip().lower() in ("y", "yes")


# Module-level singleton for convenience
_default_ui: ConsoleUI | None = None


def get_ui() -> ConsoleUI:
    """Return the module-level ConsoleUI singleton."""
    global _default_ui
    if _default_ui is None:
        _default_ui = ConsoleUI()
    return _default_ui
