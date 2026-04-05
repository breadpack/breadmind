"""CLI 세션 관리 모듈 -- 세션 저장/복원/목록 조회."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class SessionManager:
    """파일 기반 CLI 세션 관리자."""

    def __init__(self, store_dir: str | None = None) -> None:
        self._store_dir = Path(store_dir or os.path.join(Path.home(), ".breadmind", "sessions"))

    def _ensure_dir(self) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self._store_dir / f"{session_id}.json"

    def save_session(
        self,
        session_id: str,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> None:
        """세션을 JSON 파일로 저장."""
        self._ensure_dir()
        meta = metadata or {}
        now = time.time()
        if "created" not in meta:
            # 기존 파일이 있으면 created 유지
            existing = self.load_session(session_id)
            if existing is not None:
                meta["created"] = existing[1].get("created", now)
            else:
                meta["created"] = now
        meta["updated"] = now
        meta["message_count"] = len(messages)

        data = {
            "session_id": session_id,
            "messages": messages,
            "metadata": meta,
        }
        path = self._session_path(session_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_session(self, session_id: str) -> tuple[list[dict], dict] | None:
        """세션을 로드한다. 없으면 None."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", []), data.get("metadata", {})
        except (json.JSONDecodeError, KeyError):
            return None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """최근 세션 목록을 반환한다. 파일 수정 시간 기준 내림차순."""
        if not self._store_dir.exists():
            return []

        sessions = []
        for path in self._store_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                messages = data.get("messages", [])
                meta = data.get("metadata", {})

                # preview: 마지막 사용자 메시지
                preview = ""
                for msg in reversed(messages):
                    if msg.get("role") == "user" and msg.get("content"):
                        preview = msg["content"][:80]
                        break

                sessions.append({
                    "id": data.get("session_id", path.stem),
                    "preview": preview,
                    "timestamp": meta.get("updated", path.stat().st_mtime),
                    "message_count": meta.get("message_count", len(messages)),
                })
            except (json.JSONDecodeError, KeyError, OSError):
                continue

        sessions.sort(key=lambda s: s["timestamp"], reverse=True)
        return sessions[:limit]

    def get_latest_session_id(self) -> str | None:
        """가장 최근 세션 ID를 반환."""
        sessions = self.list_sessions(limit=1)
        if sessions:
            return sessions[0]["id"]
        return None

    def delete_session(self, session_id: str) -> bool:
        """세션 삭제. 성공 시 True."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False
