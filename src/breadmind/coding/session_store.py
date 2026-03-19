from __future__ import annotations

from datetime import datetime, timezone


class CodingSessionStore:
    def __init__(self, db=None):
        self._db = db
        self._memory: dict[str, dict] = {}  # fallback

    async def save_session(
        self,
        project: str,
        agent: str,
        session_id: str,
        summary: str,
    ) -> None:
        key = f"{project}:{agent}"
        entry = {
            "session_id": session_id,
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._memory[key] = entry
        if self._db:
            sessions = await self._db.get_setting("coding_sessions") or {}
            sessions[key] = entry
            await self._db.set_setting("coding_sessions", sessions)

    async def get_last_session(self, project: str, agent: str) -> str | None:
        key = f"{project}:{agent}"
        if key in self._memory:
            return self._memory[key]["session_id"]
        if self._db:
            sessions = await self._db.get_setting("coding_sessions") or {}
            if key in sessions:
                return sessions[key]["session_id"]
        return None

    async def list_sessions(self, project: str) -> list[dict]:
        results = []
        prefix = f"{project}:"
        for key, val in self._memory.items():
            if key.startswith(prefix):
                agent = key[len(prefix):]
                results.append({**val, "agent": agent})
        return results
