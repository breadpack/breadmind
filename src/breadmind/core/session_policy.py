"""Session reset policies: daily, idle, and per-channel rules."""
from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionResetPolicy:
    daily_reset_hour: int = 4  # 4 AM local time
    idle_reset_minutes: int = 30  # reset after 30min idle
    enabled: bool = True


@dataclass
class SessionState:
    session_id: str
    channel: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0


class SessionPolicyManager:
    """Manages session lifecycle with reset policies."""

    def __init__(self, default_policy: SessionResetPolicy | None = None,
                 per_channel: dict[str, SessionResetPolicy] | None = None) -> None:
        self._default = default_policy or SessionResetPolicy()
        self._per_channel = per_channel or {}
        self._sessions: dict[str, SessionState] = {}

    def get_or_create_session(self, session_id: str, channel: str) -> tuple[SessionState, bool]:
        """Get existing session or create new. Returns (session, is_new)."""
        existing = self._sessions.get(session_id)
        if existing and not self._should_reset(existing):
            existing.last_activity = time.time()
            return existing, False

        # Create new session
        state = SessionState(session_id=session_id, channel=channel)
        self._sessions[session_id] = state
        return state, True

    def record_activity(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state:
            state.last_activity = time.time()
            state.message_count += 1

    def _should_reset(self, state: SessionState) -> bool:
        policy = self._per_channel.get(state.channel, self._default)
        if not policy.enabled:
            return False

        now = time.time()

        # Idle check
        idle_seconds = now - state.last_activity
        if idle_seconds > policy.idle_reset_minutes * 60:
            logger.info("Session %s reset: idle for %d minutes",
                        state.session_id, idle_seconds // 60)
            return True

        # Daily reset check
        last_dt = datetime.datetime.fromtimestamp(state.created_at)
        now_dt = datetime.datetime.now()
        if (now_dt.date() > last_dt.date() and now_dt.hour >= policy.daily_reset_hour):
            logger.info("Session %s reset: daily reset at %dAM",
                        state.session_id, policy.daily_reset_hour)
            return True

        return False

    def cleanup_expired(self) -> int:
        """Remove sessions that should be reset."""
        to_remove = [sid for sid, state in self._sessions.items()
                     if self._should_reset(state)]
        for sid in to_remove:
            del self._sessions[sid]
        return len(to_remove)

    def get_session_info(self, session_id: str) -> dict | None:
        state = self._sessions.get(session_id)
        if not state:
            return None
        return {
            "session_id": state.session_id,
            "channel": state.channel,
            "created_at": state.created_at,
            "last_activity": state.last_activity,
            "message_count": state.message_count,
            "idle_seconds": time.time() - state.last_activity,
        }
