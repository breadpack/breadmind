from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from breadmind.memory.event_types import SignalEvent, SignalKind

# Correction lexicon (token-level partial match, lower-cased)
_CORRECTION_KO = {"아니", "아니야", "다시", "잘못", "틀렸", "다른", "그게 아니라"}
_CORRECTION_EN = {
    "no", "wrong", "incorrect", "not that", "redo", "try again", "instead",
}

_PIN_PATTERNS = [
    re.compile(r"기억\s*해\s*(줘|둬|두)"),
    re.compile(r"(이건|이거|이것)\s*(저장|기록)"),
    re.compile(r"잊지\s*마"),
    re.compile(r"\bremember\s+(this|that)\b", re.IGNORECASE),
    re.compile(r"\bkeep\s+(this|that)\s+in\s+mind\b", re.IGNORECASE),
    re.compile(r"\bpin\s+this\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class TurnSnapshot:
    user_id: str
    session_id: uuid.UUID | None
    user_message: str
    last_tool_name: str | None
    prior_turn_summary: str | None


def _matches_any(haystack: str, needles: set[str]) -> bool:
    h = haystack.lower()
    return any(n in h for n in needles)


class SignalDetector:
    """Deterministic classifier — never calls the LLM."""

    def on_tool_finished(
        self,
        snap: TurnSnapshot,
        *,
        tool_name: str,
        tool_args: dict,
        ok: bool,
        result_text: str,
    ) -> SignalEvent:
        kind = SignalKind.TOOL_EXECUTED if ok else SignalKind.TOOL_FAILED
        return SignalEvent(
            kind=kind,
            user_id=snap.user_id,
            session_id=snap.session_id,
            user_message=None,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result_text=result_text,
            prior_turn_summary=snap.prior_turn_summary,
        )

    def on_reflexion(self, snap: TurnSnapshot, *, reflexion_text: str) -> SignalEvent:
        return SignalEvent(
            kind=SignalKind.REFLEXION,
            user_id=snap.user_id,
            session_id=snap.session_id,
            user_message=reflexion_text,
            tool_name=None,
            tool_args=None,
            tool_result_text=None,
            prior_turn_summary=snap.prior_turn_summary,
        )

    def on_user_message(self, snap: TurnSnapshot) -> SignalEvent | None:
        msg = snap.user_message or ""
        if not msg.strip():
            return None
        # 1. Explicit pin
        if any(p.search(msg) for p in _PIN_PATTERNS):
            return SignalEvent(
                kind=SignalKind.EXPLICIT_PIN,
                user_id=snap.user_id,
                session_id=snap.session_id,
                user_message=msg,
                tool_name=None,
                tool_args=None,
                tool_result_text=None,
                prior_turn_summary=snap.prior_turn_summary,
            )
        # 2. User correction (requires prior tool turn)
        if snap.last_tool_name and (
            _matches_any(msg, _CORRECTION_KO) or _matches_any(msg, _CORRECTION_EN)
        ):
            return SignalEvent(
                kind=SignalKind.USER_CORRECTION,
                user_id=snap.user_id,
                session_id=snap.session_id,
                user_message=msg,
                tool_name=snap.last_tool_name,
                tool_args=None,
                tool_result_text=None,
                prior_turn_summary=snap.prior_turn_summary,
            )
        return None
