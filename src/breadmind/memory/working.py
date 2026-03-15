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
        db=None,
    ):
        self._sessions: dict[str, ConversationSession] = {}
        self._max_messages = max_messages_per_session
        self._session_timeout_minutes = session_timeout_minutes
        self._db = db

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
            if self._db and hasattr(self._db, 'save_conversation'):
                try:
                    import asyncio
                    asyncio.create_task(self._persist_session(session))
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).debug(f"Could not schedule persist: {e}")

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
            if m.role in ("user", "assistant") and (m.content and m.content.strip())
        ]

    async def _persist_session(self, session):
        """Save session to DB."""
        if not self._db:
            return
        try:
            messages = [
                {"role": m.role, "content": m.content or "",
                 "name": getattr(m, 'name', None),
                 "tool_call_id": getattr(m, 'tool_call_id', None)}
                for m in session.messages
                if m.role in ("user", "assistant")
            ]
            title = session.metadata.get("title", "")
            await self._db.save_conversation(
                session_id=session.session_id,
                user=session.user,
                channel=session.channel,
                title=title,
                messages=messages,
                created_at=session.created_at,
                last_active=session.last_active,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to persist session: {e}")

    async def load_session_from_db(self, session_id: str) -> bool:
        """Load a session from DB into working memory. Returns True if found."""
        if not self._db:
            return False
        try:
            data = await self._db.load_conversation(session_id)
            if not data:
                return False
            session = self.get_or_create_session(
                session_id, user=data.get("user", ""), channel=data.get("channel", ""))
            session.metadata["title"] = data.get("title", "")
            for msg_data in data.get("messages", []):
                msg = LLMMessage(role=msg_data["role"], content=msg_data.get("content", ""))
                session.messages.append(msg)
            # Trim to max
            if len(session.messages) > self._max_messages:
                session.messages = session.messages[-self._max_messages:]
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load session: {e}")
            return False

    async def list_all_sessions(self, user: str = "") -> list[dict]:
        """List sessions from both memory and DB."""
        summaries = self.list_session_summaries(user)
        memory_ids = {s["session_id"] for s in summaries}

        if self._db:
            try:
                db_sessions = await self._db.list_conversations(user=user)
                for s in db_sessions:
                    if s["session_id"] not in memory_ids:
                        summaries.append({
                            "session_id": s["session_id"],
                            "user": s.get("user_id", ""),
                            "channel": s.get("channel", ""),
                            "title": s.get("title", ""),
                            "message_count": 0,
                            "created_at": s["created_at"].isoformat() if s.get("created_at") else "",
                            "last_active": s["last_active"].isoformat() if s.get("last_active") else "",
                            "from_db": True,
                        })
            except Exception:
                pass

        summaries.sort(key=lambda s: s.get("last_active", ""), reverse=True)
        return summaries
