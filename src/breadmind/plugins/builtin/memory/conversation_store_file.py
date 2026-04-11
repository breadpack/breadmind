"""File-based backend for conversation storage."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from breadmind.core.protocols.provider import Message

from breadmind.plugins.builtin.memory.conversation_store import (
    ConversationMeta,
    _dict_to_message,
    _dict_to_meta,
    _message_to_dict,
    _meta_to_dict,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ConversationStoreFile:
    """File-system (JSONL) implementation of conversation storage operations."""

    def __init__(self, file_dir: str) -> None:
        self._file_dir = Path(file_dir)

    def _ensure_file_dir(self) -> Path:
        self._file_dir.mkdir(parents=True, exist_ok=True)
        return self._file_dir

    def _msg_file(self, session_id: str) -> Path:
        return self._ensure_file_dir() / f"{session_id}.jsonl"

    def _index_file(self) -> Path:
        return self._ensure_file_dir() / "index.json"

    def _read_index(self) -> list[dict[str, Any]]:
        idx = self._index_file()
        if not idx.exists():
            return []
        return json.loads(idx.read_text(encoding="utf-8"))

    def _write_index(self, entries: list[dict[str, Any]]) -> None:
        self._index_file().write_text(
            json.dumps(entries, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_message(self, session_id: str, message: Message) -> None:
        path = self._msg_file(session_id)
        line = json.dumps(_message_to_dict(message), default=str, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def save_conversation(
        self, session_id: str, messages: list[Message], meta: ConversationMeta,
    ) -> None:
        # Write messages
        path = self._msg_file(session_id)
        lines = [
            json.dumps(_message_to_dict(m), default=str, ensure_ascii=False)
            for m in messages
        ]
        path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")

        # Update index
        entries = self._read_index()
        meta_dict = _meta_to_dict(meta)
        entries = [e for e in entries if e["session_id"] != session_id]
        entries.insert(0, meta_dict)
        self._write_index(entries)

    def load_conversation(self, session_id: str) -> list[Message] | None:
        path = self._msg_file(session_id)
        if not path.exists():
            return None
        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            messages.append(_dict_to_message(json.loads(line)))
        return messages or None

    def list_conversations(
        self, user: str | None, limit: int,
    ) -> list[ConversationMeta]:
        entries = self._read_index()
        if user:
            entries = [e for e in entries if e.get("user") == user]
        # Already sorted newest-first by save_conversation insert order
        return [_dict_to_meta(e) for e in entries[:limit]]

    def delete_conversation(self, session_id: str) -> bool:
        path = self._msg_file(session_id)
        existed = path.exists()
        if existed:
            path.unlink()
        entries = self._read_index()
        new_entries = [e for e in entries if e["session_id"] != session_id]
        if len(new_entries) != len(entries):
            self._write_index(new_entries)
            existed = True
        return existed

    def search_conversations(
        self, query: str, limit: int,
    ) -> list[ConversationMeta]:
        query_lower = query.lower()
        entries = self._read_index()
        results: list[ConversationMeta] = []
        for entry in entries:
            if query_lower in entry.get("title", "").lower():
                results.append(_dict_to_meta(entry))
                if len(results) >= limit:
                    break
        return results
