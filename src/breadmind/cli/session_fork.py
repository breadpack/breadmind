"""Session branching (forking) module -- fork sessions preserving history."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionBranch:
    session_id: str
    parent_id: str
    branch_point: int  # Message index where fork happened
    created_at: float = field(default_factory=time.time)
    label: str = ""


class SessionForker:
    """Manages session branching (forking).

    --fork-session creates a new session ID when resuming,
    preserving history up to the branch point but allowing
    divergent conversation paths.
    """

    _STORAGE_FILE = "branches.json"

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or Path.home() / ".breadmind" / "sessions"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._branches: dict[str, SessionBranch] = {}
        self._load()

    def fork(
        self,
        parent_session_id: str,
        messages: list[dict],
        label: str = "",
        branch_at: int | None = None,
    ) -> SessionBranch:
        """Create a new session branch from a parent.

        If branch_at is None, branches at the end (latest message).
        """
        if branch_at is None:
            branch_at = len(messages)
        branch_at = max(0, min(branch_at, len(messages)))

        new_id = uuid.uuid4().hex[:12]
        branch = SessionBranch(
            session_id=new_id,
            parent_id=parent_session_id,
            branch_point=branch_at,
            created_at=time.time(),
            label=label,
        )
        self._branches[new_id] = branch
        self._save()
        return branch

    def get_branch(self, session_id: str) -> SessionBranch | None:
        """Get branch metadata by session ID."""
        return self._branches.get(session_id)

    def get_branch_tree(self, root_session_id: str) -> list[SessionBranch]:
        """Get all branches from a root session (direct and transitive)."""
        result: list[SessionBranch] = []
        queue = [root_session_id]
        visited: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for branch in self._branches.values():
                if branch.parent_id == current:
                    result.append(branch)
                    queue.append(branch.session_id)
        return sorted(result, key=lambda b: b.created_at)

    def get_messages_at_branch(
        self, branch: SessionBranch, all_messages: list[dict]
    ) -> list[dict]:
        """Get messages up to the branch point."""
        return all_messages[: branch.branch_point]

    def list_branches(self) -> list[SessionBranch]:
        """Return all branches sorted by creation time (newest first)."""
        return sorted(self._branches.values(), key=lambda b: b.created_at, reverse=True)

    def _save(self) -> None:
        path = self._storage_dir / self._STORAGE_FILE
        data = {
            sid: {
                "session_id": b.session_id,
                "parent_id": b.parent_id,
                "branch_point": b.branch_point,
                "created_at": b.created_at,
                "label": b.label,
            }
            for sid, b in self._branches.items()
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        path = self._storage_dir / self._STORAGE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for sid, entry in raw.items():
            self._branches[sid] = SessionBranch(
                session_id=entry["session_id"],
                parent_id=entry["parent_id"],
                branch_point=entry["branch_point"],
                created_at=entry.get("created_at", 0),
                label=entry.get("label", ""),
            )
