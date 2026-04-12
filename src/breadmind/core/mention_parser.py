"""Parse @-mention file references in user messages to resolve file content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileMention:
    """A parsed @-mention file reference."""

    raw: str  # Original mention text, e.g., "@src/main.py:10-20"
    file_path: str  # Resolved path
    start_line: int | None = None
    end_line: int | None = None
    label: str = ""  # Optional label


@dataclass
class TerminalMention:
    """A parsed @terminal: reference."""

    raw: str
    name: str


class MentionParser:
    """Parse @-mention file references in user messages.

    Supported formats:
    - @file.py              -- whole file
    - @file.py:10           -- single line
    - @file.py:10-20        -- line range
    - @src/dir/file.py:L10  -- with L prefix
    - @src/dir/file.py:L10-L20  -- with L prefix range
    - @terminal:name        -- terminal output reference
    """

    # Match @path/to/file.ext optionally followed by :line or :line-line
    PATTERN = re.compile(
        r"@([\w./\\-]+\.[\w]+)(?::L?(\d+)(?:-L?(\d+))?)?"
    )
    TERMINAL_PATTERN = re.compile(r"@terminal:(\w+)")

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()

    def parse(self, text: str) -> list[FileMention]:
        """Extract all file mentions from text."""
        mentions: list[FileMention] = []
        for match in self.PATTERN.finditer(text):
            raw = match.group(0)
            file_path = match.group(1)
            start_str = match.group(2)
            end_str = match.group(3)

            # Strip line-range suffix from file_path if present
            # (the regex captures file.ext separately from :line)
            start_line = int(start_str) if start_str else None
            end_line = int(end_str) if end_str else None

            # If only start_line given, end_line == start_line (single line)
            if start_line is not None and end_line is None:
                end_line = start_line

            resolved = self._resolve_path(file_path)
            mentions.append(
                FileMention(
                    raw=raw,
                    file_path=resolved,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
        return mentions

    def parse_terminals(self, text: str) -> list[TerminalMention]:
        """Extract terminal mentions from text."""
        results: list[TerminalMention] = []
        for match in self.TERMINAL_PATTERN.finditer(text):
            results.append(
                TerminalMention(raw=match.group(0), name=match.group(1))
            )
        return results

    def resolve_content(self, mention: FileMention) -> str | None:
        """Read file content for a mention, respecting line ranges.

        Returns None if file doesn't exist.
        """
        path = Path(mention.file_path)
        if not path.is_absolute():
            path = self._root / path

        if not path.is_file():
            return None

        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            return None

        if mention.start_line is not None and mention.end_line is not None:
            # Line numbers are 1-based
            start = max(0, mention.start_line - 1)
            end = min(len(lines), mention.end_line)
            return "".join(lines[start:end])

        return "".join(lines)

    def expand_mentions(self, text: str) -> tuple[str, list[dict]]:
        """Replace @mentions in text with resolved content.

        Returns (cleaned_text, list of context dicts).
        Each context dict has keys: raw, file_path, start_line, end_line, content.
        """
        mentions = self.parse(text)
        contexts: list[dict] = []
        cleaned = text

        for mention in mentions:
            content = self.resolve_content(mention)
            ctx: dict = {
                "raw": mention.raw,
                "file_path": mention.file_path,
                "start_line": mention.start_line,
                "end_line": mention.end_line,
                "content": content,
            }
            contexts.append(ctx)

            if content is not None:
                # Remove the @mention from text (will be injected as context)
                cleaned = cleaned.replace(mention.raw, "")

        # Collapse multiple spaces left by removal
        cleaned = re.sub(r"  +", " ", cleaned).strip()
        return cleaned, contexts

    def _resolve_path(self, file_path: str) -> str:
        """Resolve a relative file path against the project root."""
        p = Path(file_path)
        if p.is_absolute():
            return str(p)
        resolved = self._root / p
        return str(resolved)
