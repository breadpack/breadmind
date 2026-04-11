import logging
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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

    def check(self, action: str, params: dict, user: str, channel: str, agent_id: str | None = None) -> SafetyResult:
        # Role-based policy checking for distributed agents
        if agent_id and hasattr(self, '_agent_policies'):
            policies = self._agent_policies.get(agent_id, {})
            blocked = policies.get("blocked", [])
            if action in blocked:
                return SafetyResult.DENY

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

    def reload(
        self,
        *,
        blacklist=None,
        approval=None,
        permissions=None,
        tool_security=None,
    ) -> None:
        """Replace live rule sets from new settings.

        ``None`` means keep current. Accepts:

        - ``blacklist``: dict mapping category -> list of tool names, OR a
          flat list of tool names (normalized to ``{"default": [...]}``).
        - ``approval``: list/iterable of tool names requiring approval, OR
          a dict whose keys are tool names.
        - ``permissions``: dict with either ``{"user_permissions": {...},
          "admin_users": [...]}`` or the raw user_permissions mapping. An
          ``admin_users`` alias key is also accepted at the top level.
        - ``tool_security``: currently a no-op on SafetyGuard — the tool
          security allowlist is consulted by the ToolRegistry/executor
          rather than cached on the guard, so nothing to swap here. We
          still log at debug level so hot-reload wiring stays observable.
        """
        if blacklist is not None:
            if isinstance(blacklist, dict):
                normalized: dict[str, list[str]] = {
                    str(k): list(v or []) for k, v in blacklist.items()
                }
            else:
                normalized = {"default": list(blacklist)}
            self._blacklist = normalized
            self._flat_blacklist = set()
            for actions in self._blacklist.values():
                self._flat_blacklist.update(actions)

        if approval is not None:
            if isinstance(approval, dict):
                tools = list(approval.keys())
            else:
                tools = list(approval)
            self._require_approval = set(tools)

        if permissions is not None:
            if isinstance(permissions, dict):
                if (
                    "user_permissions" in permissions
                    or "admin_users" in permissions
                ):
                    user_perms = permissions.get("user_permissions") or {}
                    admins = permissions.get("admin_users")
                    self._user_permissions = dict(user_perms)
                    if admins is not None:
                        self._admin_users = list(admins)
                else:
                    self._user_permissions = dict(permissions)
            else:
                # A bare list/iterable is interpreted as the admin_users
                # alias payload (safety_permissions_admin_users key).
                self._admin_users = list(permissions)

        if tool_security is not None:
            logger.debug(
                "SafetyGuard.reload: tool_security is not cached on the "
                "guard; ignoring payload (keys=%s)",
                list(tool_security.keys())
                if isinstance(tool_security, dict)
                else type(tool_security).__name__,
            )

    def get_config(self) -> dict:
        """Return current safety config as dict."""
        return {
            "blacklist": self._blacklist if hasattr(self, '_blacklist') else {},
            "require_approval": list(self._require_approval),
            "user_permissions": self._user_permissions,
            "admin_users": self._admin_users,
        }

    def merge_plugin_safety(self, plugin_name: str, safety_decl: dict) -> None:
        """Merge safety declarations from a plugin manifest.

        Plugin declarations are defaults; the central safety.yaml overrides.
        Tools not declared anywhere default to deny (deny-by-default for
        unknown plugins is enforced at the PluginManager level).
        """
        # Merge require_approval
        for tool_name in safety_decl.get("require_approval", []):
            self._require_approval.add(tool_name)
        # Merge blacklist
        bl_tools = safety_decl.get("blacklist", [])
        if bl_tools:
            existing = self._blacklist.get(plugin_name, [])
            self._blacklist[plugin_name] = list(set(existing) | set(bl_tools))
            self._flat_blacklist.update(bl_tools)

    def set_agent_policies(self, agent_id: str, policies: dict) -> None:
        if not hasattr(self, '_agent_policies'):
            self._agent_policies = {}
        self._agent_policies[agent_id] = policies

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
