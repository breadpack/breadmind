from dataclasses import dataclass, field
from datetime import datetime, timezone
from breadmind.llm.base import LLMMessage

@dataclass
class ConversationSession:
    session_id: str
    user: str
    channel: str
    messages: list[LLMMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

class WorkingMemory:
    """Layer 1: In-memory working memory for active conversations."""

    def __init__(
        self,
        max_messages_per_session: int = 50,
        session_timeout_minutes: int = 30,
    ):
        self._sessions: dict[str, ConversationSession] = {}
        self._max_messages = max_messages_per_session
        self._session_timeout_minutes = session_timeout_minutes

    def get_or_create_session(self, session_id: str, user: str = "", channel: str = "") -> ConversationSession:
        session = self._sessions.get(session_id)
        if session is not None:
            now = datetime.now(timezone.utc)
            elapsed = (now - session.last_active).total_seconds()
            if elapsed >= self._session_timeout_minutes * 60:
                # Session expired — clear and recreate
                self._sessions.pop(session_id)
                session = None

        if session is None:
            session = ConversationSession(
                session_id=session_id, user=user, channel=channel,
            )
            self._sessions[session_id] = session

        session.last_active = datetime.now(timezone.utc)
        return session

    def add_message(self, session_id: str, message: LLMMessage):
        session = self._sessions.get(session_id)
        if session:
            session.messages.append(message)
            session.last_active = datetime.now(timezone.utc)
            if len(session.messages) > self._max_messages:
                session.messages = session.messages[-self._max_messages:]

    def get_messages(self, session_id: str) -> list[LLMMessage]:
        session = self._sessions.get(session_id)
        return session.messages if session else []

    def clear_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    def cleanup_expired(self) -> list[str]:
        """Remove all expired sessions. Returns list of removed session IDs."""
        now = datetime.now(timezone.utc)
        expired = []
        for sid, session in list(self._sessions.items()):
            elapsed = (now - session.last_active).total_seconds()
            if elapsed >= self._session_timeout_minutes * 60:
                expired.append(sid)
                self._sessions.pop(sid)
        return expired

    def update_config(self, max_messages: int = None, timeout_minutes: int = None):
        """Update memory configuration at runtime."""
        if max_messages is not None and max_messages >= 1:
            self._max_messages = max_messages
        if timeout_minutes is not None and timeout_minutes >= 1:
            self._session_timeout_minutes = timeout_minutes

    def get_config(self) -> dict:
        return {
            "max_messages_per_session": self._max_messages,
            "session_timeout_minutes": self._session_timeout_minutes,
            "active_sessions": len(self._sessions),
        }

    def get_session_summary(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if not session:
            return {}
        return {
            "session_id": session.session_id,
            "user": session.user,
            "channel": session.channel,
            "title": session.metadata.get("title", ""),
            "message_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "last_active": session.last_active.isoformat(),
        }

    def list_session_summaries(self, user: str = "") -> list[dict]:
        """Return summaries of all sessions, optionally filtered by user."""
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.last_active, reverse=True,
        )
        if user:
            sessions = [s for s in sessions if s.user == user]
        return [self.get_session_summary(s.session_id) for s in sessions]

    def set_session_title(self, session_id: str, title: str):
        session = self._sessions.get(session_id)
        if session:
            session.metadata["title"] = title

    def get_session_messages(self, session_id: str) -> list[dict]:
        """Return messages in a serializable format."""
        session = self._sessions.get(session_id)
        if not session:
            return []
        return [
            {"role": m.role, "content": m.content or ""}
            for m in session.messages
            if m.role in ("user", "assistant")
        ]
