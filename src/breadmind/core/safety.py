from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

class SafetyResult(Enum):
    ALLOW = "ALLOWED"
    DENY = "DENIED"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"

class SafetyGuard:
    def __init__(
        self,
        blacklist: dict[str, list[str]] | None = None,
        require_approval: list[str] | None = None,
    ):
        self._blacklist = blacklist or {}
        self._require_approval = set(require_approval or [])
        self._flat_blacklist = set()
        for actions in self._blacklist.values():
            self._flat_blacklist.update(actions)
        self._cooldowns: dict[str, datetime] = {}

    def check(self, action: str, params: dict, user: str, channel: str) -> SafetyResult:
        if action in self._flat_blacklist:
            return SafetyResult.DENY
        if action in self._require_approval:
            return SafetyResult.REQUIRE_APPROVAL
        return SafetyResult.ALLOW

    def check_cooldown(self, target: str, action: str, cooldown_minutes: int = 10) -> bool:
        """Returns True if action is allowed (not in cooldown)."""
        key = f"{target}:{action}"
        now = datetime.utcnow()
        last = self._cooldowns.get(key)
        if last and (now - last).total_seconds() < cooldown_minutes * 60:
            return False
        self._cooldowns[key] = now
        return True
