from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

class SafetyResult(Enum):
    ALLOW = "ALLOWED"
    DENY = "DENIED"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"

class SafetyGuard:
    def __init__(
        self,
        blacklist: dict[str, list[str]] | None = None,
        require_approval: list[str] | None = None,
        user_permissions: dict[str, list[str]] | None = None,
        admin_users: list[str] | None = None,
    ):
        self._blacklist = blacklist or {}
        self._require_approval = set(require_approval or [])
        self._flat_blacklist = set()
        for actions in self._blacklist.values():
            self._flat_blacklist.update(actions)
        self._cooldowns: dict[str, datetime] = {}
        self._cooldown_check_count: int = 0
        self._user_permissions: dict[str, list[str]] = user_permissions or {}
        self._admin_users: list[str] = admin_users or []

    def check(self, action: str, params: dict, user: str, channel: str) -> SafetyResult:
        # Admin users bypass all checks
        if user in self._admin_users:
            return SafetyResult.ALLOW

        # User permissions check (only if configured)
        if self._user_permissions:
            if user not in self._user_permissions:
                return SafetyResult.DENY
            allowed_tools = self._user_permissions[user]
            if allowed_tools and action not in allowed_tools:
                return SafetyResult.DENY

        if action in self._flat_blacklist:
            return SafetyResult.DENY
        if action in self._require_approval:
            return SafetyResult.REQUIRE_APPROVAL
        return SafetyResult.ALLOW

    def update_blacklist(self, blacklist: dict):
        """Replace blacklist. blacklist = {"kubernetes": ["k8s_delete_namespace", ...], ...}"""
        self._blacklist = blacklist
        self._flat_blacklist = set()
        for tools in blacklist.values():
            self._flat_blacklist.update(tools)

    def update_require_approval(self, tools: list[str]):
        """Replace require_approval list."""
        self._require_approval = set(tools)

    def update_user_permissions(self, permissions: dict[str, list[str]], admins: list[str] = None):
        """Update user permissions and admin list."""
        self._user_permissions = permissions
        if admins is not None:
            self._admin_users = admins

    def get_config(self) -> dict:
        """Return current safety config as dict."""
        return {
            "blacklist": self._blacklist if hasattr(self, '_blacklist') else {},
            "require_approval": list(self._require_approval),
            "user_permissions": self._user_permissions,
            "admin_users": self._admin_users,
        }

    def check_cooldown(self, target: str, action: str, cooldown_minutes: int = 10) -> bool:
        """Returns True if action is allowed (not in cooldown)."""
        self._cooldown_check_count += 1
        if self._cooldown_check_count % 100 == 0:
            self._cleanup_expired_cooldowns(cooldown_minutes)

        key = f"{target}:{action}"
        now = datetime.now(timezone.utc)
        last = self._cooldowns.get(key)
        if last and (now - last).total_seconds() < cooldown_minutes * 60:
            return False
        self._cooldowns[key] = now
        return True

    def _cleanup_expired_cooldowns(self, default_cooldown_minutes: int = 10) -> None:
        """Remove expired cooldown entries."""
        now = datetime.now(timezone.utc)
        threshold = default_cooldown_minutes * 60
        expired = [
            k for k, v in self._cooldowns.items()
            if (now - v).total_seconds() >= threshold
        ]
        for k in expired:
            del self._cooldowns[k]
