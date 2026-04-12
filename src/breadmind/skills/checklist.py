from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChecklistState:
    session_id: str
    skill_name: str
    steps: list[str]
    completed_count: int = 0

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def is_done(self) -> bool:
        return self.completed_count >= self.total

    @property
    def current_step(self) -> str:
        if self.is_done:
            return ""
        return self.steps[self.completed_count]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "skill_name": self.skill_name,
            "steps": list(self.steps),
            "completed_count": self.completed_count,
            "total": self.total,
            "current_step": self.current_step,
            "is_done": self.is_done,
        }


class ChecklistTracker:
    """In-memory tracker for skill checklist progress. No persistence."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], ChecklistState] = {}

    def start(self, session_id: str, skill_name: str, *, steps: list[str]) -> ChecklistState:
        state = ChecklistState(
            session_id=session_id, skill_name=skill_name, steps=list(steps),
        )
        self._state[(session_id, skill_name)] = state
        return state

    def advance(self, session_id: str, skill_name: str) -> ChecklistState | None:
        state = self._state.get((session_id, skill_name))
        if state is None:
            return None
        if state.completed_count < state.total:
            state.completed_count += 1
        return state

    def get(self, session_id: str, skill_name: str) -> ChecklistState | None:
        return self._state.get((session_id, skill_name))

    def clear_session(self, session_id: str) -> None:
        for key in [k for k in self._state if k[0] == session_id]:
            del self._state[key]

    def summary(self, session_id: str) -> list[dict[str, Any]]:
        return [
            s.to_dict()
            for (sid, _name), s in self._state.items()
            if sid == session_id
        ]


_global_tracker: ChecklistTracker | None = None


def get_checklist_tracker() -> ChecklistTracker:
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = ChecklistTracker()
    return _global_tracker
