"""v2 WorkingMemory: 세션별 대화 히스토리 관리."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from breadmind.core.protocols import Message


@dataclass
class Session:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WorkingMemory:
    """세션별 워킹 메모리. MemoryProtocol의 working_* 메서드 구현."""

    def __init__(
        self,
        max_messages: int = 50,
        compress_threshold: int = 30,
        keep_recent: int = 10,
        session_timeout_minutes: int = 30,
        compressor: Any = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_messages = max_messages
        self._compress_threshold = compress_threshold
        self._keep_recent = keep_recent
        self._timeout_minutes = session_timeout_minutes
        self._compressor = compressor

    async def working_get(self, session_id: str) -> list[Message]:
        session = self._get_session(session_id)
        if session is None:
            return []
        return list(session.messages)

    async def working_put(self, session_id: str, messages: list[Message]) -> None:
        session = self._get_or_create(session_id)
        session.messages = list(messages)
        session.last_active = datetime.now(timezone.utc)

        if len(session.messages) >= self._compress_threshold and self._compressor:
            await self.working_compress(session_id, budget=self._keep_recent)
        elif len(session.messages) > self._max_messages:
            session.messages = session.messages[-self._max_messages:]

    async def working_compress(self, session_id: str, budget: int) -> None:
        session = self._get_session(session_id)
        if session is None or len(session.messages) <= budget:
            return

        if self._compressor:
            try:
                old_messages = session.messages[:-self._keep_recent]
                recent = session.messages[-self._keep_recent:]
                summary = await self._compressor.summarize(old_messages)
                session.messages = [
                    Message(role="system", content=f"[Previous conversation summary]: {summary}"),
                    *recent,
                ]
                return
            except Exception:
                pass

        # Fallback: simple truncation
        session.messages = session.messages[-budget:]

    def get_session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s.last_active).total_seconds() >= self._timeout_minutes * 60
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def _get_session(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        now = datetime.now(timezone.utc)
        if (now - session.last_active).total_seconds() >= self._timeout_minutes * 60:
            del self._sessions[session_id]
            return None
        return session

    def _get_or_create(self, session_id: str) -> Session:
        session = self._get_session(session_id)
        if session is None:
            session = Session(session_id=session_id)
            self._sessions[session_id] = session
        return session
