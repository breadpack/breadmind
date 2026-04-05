"""Startup file resource loader for --file CLI flag."""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileResource:
    """A file loaded at session startup."""

    name: str
    content: str
    source: str  # "local", "alias"
    size: int = 0
    mime_type: str = "text/plain"


class FileTooLargeError(Exception):
    """Raised when a file exceeds the maximum allowed size."""

    def __init__(self, path: str, size: int, max_size: int) -> None:
        self.path = path
        self.size = size
        self.max_size = max_size
        super().__init__(
            f"File '{path}' is {size} bytes, exceeds max {max_size} bytes"
        )


class TooManyFilesError(Exception):
    """Raised when too many files are requested."""

    def __init__(self, count: int, max_files: int) -> None:
        self.count = count
        self.max_files = max_files
        super().__init__(
            f"Requested {count} files, exceeds max {max_files}"
        )


class StartupFileLoader:
    """Load file resources at session startup.

    Supports:
    - Local file paths: ``--file src/main.py``
    - Named aliases: ``--file alias:doc.txt``
    - Multiple files: ``--file a.py b.py c.py``
    """

    def __init__(
        self,
        max_file_size: int = 100_000,
        max_files: int = 20,
    ) -> None:
        self._max_size = max_file_size
        self._max_files = max_files
        self._resources: list[FileResource] = []

    def load(self, file_specs: list[str]) -> list[FileResource]:
        """Load files from specs (paths or alias:name pairs).

        Raises :class:`TooManyFilesError` if the number of specs exceeds
        the configured maximum.
        """
        if len(file_specs) > self._max_files:
            raise TooManyFilesError(len(file_specs), self._max_files)

        resources: list[FileResource] = []
        for spec in file_specs:
            source, path_or_id = self.parse_spec(spec)
            if source == "alias":
                # Alias resolution would be handled by a registry; for now
                # treat the right-hand side as a local path.
                resource = self.load_local(path_or_id)
                resource.source = "alias"
            else:
                resource = self.load_local(path_or_id)
            resources.append(resource)

        self._resources.extend(resources)
        return resources

    def load_local(self, path: str) -> FileResource:
        """Load a local file.

        Raises :class:`FileTooLargeError` if the file exceeds the max size.
        Raises :class:`FileNotFoundError` if the file does not exist.
        """
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        size = p.stat().st_size
        if size > self._max_size:
            raise FileTooLargeError(path, size, self._max_size)

        content = p.read_text(encoding="utf-8", errors="replace")
        mime, _ = mimetypes.guess_type(str(p))

        return FileResource(
            name=p.name,
            content=content,
            source="local",
            size=size,
            mime_type=mime or "text/plain",
        )

    @staticmethod
    def parse_spec(spec: str) -> tuple[str, str]:
        """Parse ``'alias:name'`` or plain path spec.

        Returns ``(source, path_or_id)`` where source is ``'alias'`` or
        ``'local'``.
        """
        if ":" in spec:
            prefix, _, rest = spec.partition(":")
            # Avoid treating Windows drive letters (e.g. C:\\) as aliases
            if len(prefix) == 1 and prefix.isalpha():
                return "local", spec
            return "alias", rest
        return "local", spec

    def build_context_messages(self) -> list[dict]:
        """Build system messages containing loaded file contents."""
        messages: list[dict] = []
        for res in self._resources:
            messages.append({
                "role": "system",
                "content": (
                    f"--- File: {res.name} (source: {res.source}, "
                    f"{res.size} bytes) ---\n{res.content}"
                ),
            })
        return messages

    @property
    def resources(self) -> list[FileResource]:
        return list(self._resources)

    @property
    def total_size(self) -> int:
        return sum(r.size for r in self._resources)
