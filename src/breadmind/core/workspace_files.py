"""Structured workspace file system (SOUL.md, AGENTS.md, TOOLS.md, etc.)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceFile:
    name: str  # e.g. "SOUL.md"
    purpose: str  # "personality", "rules", "tools", "memory", "identity"
    content: str = ""
    max_chars: int = 4000
    inject_mode: str = "always"  # "always" (every session) or "on_demand"


WORKSPACE_FILES = [
    WorkspaceFile("SOUL.md", "personality", max_chars=4000, inject_mode="always"),
    WorkspaceFile("AGENTS.md", "rules", max_chars=4000, inject_mode="always"),
    WorkspaceFile("TOOLS.md", "tools", max_chars=2000, inject_mode="always"),
    WorkspaceFile("MEMORY.md", "memory", max_chars=4000, inject_mode="always"),
    WorkspaceFile("USER.md", "user", max_chars=2000, inject_mode="always"),
    WorkspaceFile("IDENTITY.md", "identity", max_chars=1000, inject_mode="always"),
    WorkspaceFile(
        "HEARTBEAT.md", "heartbeat", max_chars=2000, inject_mode="on_demand"
    ),
]


class WorkspaceFileManager:
    """Manages structured workspace files for agent prompt injection."""

    def __init__(self, workspace_dir: str, total_max_chars: int = 16000) -> None:
        self._workspace_dir = workspace_dir
        self._total_max_chars = total_max_chars
        self._files: dict[str, WorkspaceFile] = {}
        self._load_all()

    def _load_all(self) -> None:
        for wf in WORKSPACE_FILES:
            path = os.path.join(self._workspace_dir, wf.name)
            loaded = WorkspaceFile(
                name=wf.name,
                purpose=wf.purpose,
                max_chars=wf.max_chars,
                inject_mode=wf.inject_mode,
            )
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    loaded.content = content[:wf.max_chars]
                except (IOError, OSError):
                    pass
            self._files[wf.name] = loaded

    def reload(self) -> None:
        """Reload all workspace files from disk."""
        self._load_all()

    def get_injection_blocks(self, mode: str = "always") -> list[dict]:
        """Get workspace file contents for prompt injection.

        Returns [{"section": "...", "content": "...", "file_name": "..."}]
        for files matching mode.
        """
        blocks = []
        total = 0
        for wf in self._files.values():
            if wf.inject_mode != mode or not wf.content:
                continue
            if total + len(wf.content) > self._total_max_chars:
                break
            blocks.append({
                "section": f"workspace:{wf.purpose}",
                "content": f"[{wf.name}]\n{wf.content}",
                "file_name": wf.name,
            })
            total += len(wf.content)
        return blocks

    def get_file(self, name: str) -> WorkspaceFile | None:
        return self._files.get(name)

    def update_file(self, name: str, content: str) -> bool:
        wf = self._files.get(name)
        if wf is None:
            return False
        wf.content = content[:wf.max_chars]
        path = os.path.join(self._workspace_dir, name)
        try:
            os.makedirs(self._workspace_dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(wf.content)
            return True
        except (IOError, OSError):
            return False

    def list_files(self) -> list[dict]:
        return [
            {
                "name": wf.name,
                "purpose": wf.purpose,
                "chars": len(wf.content),
                "max_chars": wf.max_chars,
                "mode": wf.inject_mode,
            }
            for wf in self._files.values()
        ]

    def get_total_chars(self) -> int:
        return sum(
            len(wf.content)
            for wf in self._files.values()
            if wf.inject_mode == "always"
        )
