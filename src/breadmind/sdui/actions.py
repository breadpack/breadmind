"""Action handler: processes user actions from the SDUI renderer.

Action message shape:
    {"kind": "intervention", "flow_id": ..., "step_id": ..., "value": ...}
    {"kind": "chat_input", "session_id": ..., "values": {"text": ...}}
    {"kind": "view_request", "view_key": ..., "params": ...}  # handled in ws route directly
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable
from uuid import UUID

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)


MessageHandler = Callable[..., Awaitable[str]]


class ActionHandler:
    """Dispatch SDUI action messages to the appropriate handler.

    Phase 1 only handled :class:`FlowEvent` interventions. Phase 1.5 adds
    chat input: when a ``message_handler`` and ``working_memory`` are
    provided, ``chat_input`` actions are forwarded to the CoreAgent via
    the message handler. The working memory is used by the chat view
    (not directly by this handler) to render the updated conversation.
    """

    def __init__(
        self,
        bus: FlowEventBus,
        *,
        message_handler: MessageHandler | None = None,
        working_memory: Any = None,
        settings_store: Any = None,
        credential_vault: Any = None,
    ) -> None:
        self._bus = bus
        self._message_handler = message_handler
        self._working_memory = working_memory
        self._settings_store = settings_store
        self._credential_vault = credential_vault

    async def handle(self, action: dict[str, Any], *, user_id: str) -> dict[str, Any]:
        kind = action.get("kind")
        if kind == "intervention":
            return await self._intervention(action, user_id)
        if kind == "view_request":
            # The WS route handles navigation directly; this is a no-op for completeness.
            return {
                "ok": True,
                "view_key": action.get("view_key"),
                "params": action.get("params", {}),
            }
        if kind == "chat_input":
            return await self._chat_input(action, user_id)
        if kind == "settings_write":
            return await self._settings_write(action, user_id)
        if kind == "settings_append":
            return await self._settings_append(action, user_id)
        if kind == "dev_inject_assistant":
            return await self._dev_inject_assistant(action, user_id)
        return {"ok": False, "error": f"unknown action kind: {kind}"}

    async def _dev_inject_assistant(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Inject a fake assistant message directly into working memory.

        Used for SDUI widget rendering smoke tests when no LLM provider is
        available. The action body must contain ``content`` (str) and may
        optionally specify ``session_id``.
        """
        if self._working_memory is None:
            return {"ok": False, "error": "working_memory not configured"}
        content = action.get("content")
        if not isinstance(content, str) or not content:
            return {"ok": False, "error": "content must be a non-empty string"}
        session_id = action.get("session_id") or f"sdui:{user_id}"

        try:
            from breadmind.llm.base import LLMMessage
            self._working_memory.get_or_create_session(
                session_id, user=user_id, channel=session_id
            )
            self._working_memory.add_message(
                session_id,
                LLMMessage(role="assistant", content=content),
            )
        except Exception as exc:
            logger.warning("dev_inject_assistant failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "refresh_view": "chat_view"}

    async def _chat_input(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        values = action.get("values") or {}
        text = (values.get("text") or "").strip()
        session_id = action.get("session_id") or f"sdui:{user_id}"

        if not text:
            return {"ok": True, "refresh_view": "chat_view", "noop": True}

        if self._message_handler is None:
            # Graceful degradation: keep the Phase 1 behaviour for tests
            # and environments that have no CoreAgent wired up.
            return {"ok": True, "deferred": "chat_handler"}

        try:
            await self._message_handler(text, user=user_id, channel=session_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("chat_input message_handler failed: %s", exc)
            return {"ok": False, "error": str(exc), "refresh_view": "chat_view"}

        return {"ok": True, "refresh_view": "chat_view"}

    async def _intervention(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        try:
            flow_id = UUID(str(action["flow_id"]))
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "error": "invalid or missing flow_id"}
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.USER_INTERVENTION,
                payload={
                    "step_id": action.get("step_id"),
                    "action": action.get("value"),
                    "user_id": user_id,
                    "metadata": action.get("metadata", {}),
                },
                actor=FlowActor.USER,
            )
        )
        return {"ok": True}

    async def _settings_write(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Persist a Phase 1 setting via settings_store or credential_vault.

        Whitelisted keys only — see ``settings_schema.is_allowed_key``.
        """
        from breadmind.sdui.settings_schema import (
            SettingsValidationError,
            is_allowed_key,
            is_credential_key,
            requires_restart,
            validate_value,
        )

        key = action.get("key")
        if not isinstance(key, str) or not is_allowed_key(key):
            return {"ok": False, "error": f"key not allowed: {key}"}

        # Admin-only key check.
        if key in self._ADMIN_ONLY_KEYS:
            if not await self._is_admin(user_id):
                return {"ok": False, "error": "permission denied: admin only"}

        raw_value = action.get("values")
        try:
            cleaned = validate_value(key, raw_value)
        except SettingsValidationError as exc:
            return {"ok": False, "error": str(exc)}

        if is_credential_key(key):
            if self._credential_vault is None:
                return {"ok": False, "error": "credential vault not configured"}
            try:
                await self._credential_vault.store(key, cleaned, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("settings_write vault.store failed: %s", exc)
                return {"ok": False, "error": str(exc)}
        else:
            if self._settings_store is None:
                return {"ok": False, "error": "settings_store not configured"}
            try:
                existing = await self._settings_store.get_setting(key)
            except Exception:
                existing = None
            if isinstance(existing, dict) and isinstance(cleaned, dict):
                merged = {**existing, **cleaned}
            else:
                merged = cleaned
            try:
                await self._settings_store.set_setting(key, merged)
            except Exception as exc:  # noqa: BLE001
                logger.warning("settings_write set_setting failed: %s", exc)
                return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "persisted": True,
            "restart_required": requires_restart(key),
            "refresh_view": "settings_view",
        }

    # ------------------------------------------------------------------
    # Admin-only keys — writes/appends require the user to be in
    # safety_permissions.admin_users.  If admin_users is empty/missing,
    # NOBODY is admin and these writes are blocked, with one exception:
    # when admin_users is empty and the key is safety_permissions_admin_users,
    # the write is allowed so the first operator can bootstrap admin access.
    # ------------------------------------------------------------------
    _ADMIN_ONLY_KEYS: frozenset[str] = frozenset(
        {
            "safety_blacklist",
            "safety_approval",
            "safety_permissions",
            "safety_permissions_admin_users",
            "tool_security",
            "system_timeouts",
            "retry_config",
            "limits_config",
            "polling_config",
            "agent_timeouts",
            "logging_config",
        }
    )

    async def _is_admin(self, user_id: str) -> bool:
        """Return True iff user_id appears in safety_permissions.admin_users."""
        if self._settings_store is None:
            return False
        try:
            perms = await self._settings_store.get_setting("safety_permissions")
        except Exception:  # noqa: BLE001
            return False
        if not isinstance(perms, dict):
            return False
        admin_users = perms.get("admin_users") or []
        return bool(user_id and user_id in admin_users)

    # ------------------------------------------------------------------
    # Allowed keys for settings_append (list/dict-shaped settings only)
    # ------------------------------------------------------------------
    _APPEND_ALLOWED_KEYS = frozenset(
        {
            "mcp_servers",
            "skill_markets",
            "safety_approval",
            "safety_blacklist",
            "safety_permissions_admin_users",
            "scheduler_cron",
        }
    )

    async def _settings_append(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Append a single item to a list- or dict-shaped setting.

        Whitelisted keys only — see ``_APPEND_ALLOWED_KEYS``.
        The incoming ``values`` payload is a *single item* (not the full list).
        The handler reads the existing value, merges, re-validates the full
        candidate via ``validate_value``, then persists.
        """
        from breadmind.sdui.settings_schema import (
            SettingsValidationError,
            validate_value,
        )

        key = action.get("key")
        if key not in self._APPEND_ALLOWED_KEYS:
            return {"ok": False, "error": f"key not allowed for settings_append: {key}"}

        if self._settings_store is None:
            return {"ok": False, "error": "settings_store not configured"}

        # Admin-only key check.
        # Bootstrap exception: when admin_users is empty/missing AND the key is
        # safety_permissions_admin_users, allow the write so the first user can
        # become admin without being locked out.
        if key in self._ADMIN_ONLY_KEYS:
            is_bootstrap = False
            if key == "safety_permissions_admin_users":
                try:
                    perms = await self._settings_store.get_setting("safety_permissions")
                except Exception:  # noqa: BLE001
                    perms = None
                existing_admin_users = (
                    perms.get("admin_users") or []
                    if isinstance(perms, dict)
                    else []
                )
                is_bootstrap = len(existing_admin_users) == 0
            if not is_bootstrap and not await self._is_admin(user_id):
                return {"ok": False, "error": "permission denied: admin only"}

        item = action.get("values")

        # Delegate to specialised helpers per key type.
        if key == "safety_permissions_admin_users":
            return await self._append_admin_user(item)

        if key == "safety_blacklist":
            return await self._append_blacklist_entry(item, validate_value, SettingsValidationError)

        # All remaining keys are list-shaped; build candidate and validate.
        try:
            existing = await self._settings_store.get_setting(key)
        except Exception:
            existing = None

        existing_list: list = existing if isinstance(existing, list) else []

        if key == "mcp_servers":
            merged, err = self._merge_mcp_server(existing_list, item)
        elif key == "skill_markets":
            merged, err = self._merge_skill_market(existing_list, item)
        elif key == "safety_approval":
            merged, err = self._merge_safety_approval(existing_list, item)
        elif key == "scheduler_cron":
            merged, err = self._merge_scheduler_cron(existing_list, item)
        else:
            return {"ok": False, "error": f"key not allowed for settings_append: {key}"}

        if err is not None:
            return {"ok": False, "error": err}

        try:
            cleaned = validate_value(key, merged)
        except SettingsValidationError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            await self._settings_store.set_setting(key, cleaned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings_append set_setting failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

    # ------------------------------------------------------------------
    # Per-key merge helpers (return (merged_candidate, error_str|None))
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_mcp_server(
        existing: list, item: Any
    ) -> tuple[list | None, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "mcp_servers item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"mcp_servers: duplicate name {name!r}"
        return existing + [item], None

    @staticmethod
    def _merge_skill_market(
        existing: list, item: Any
    ) -> tuple[list | None, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "skill_markets item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"skill_markets: duplicate name {name!r}"
        return existing + [item], None

    @staticmethod
    def _merge_safety_approval(
        existing: list, item: Any
    ) -> tuple[list | None, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object with a 'tool' field"
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool:
            return None, "safety_approval item: tool must be a non-empty string"
        if tool in existing:
            return None, f"safety_approval: duplicate tool {tool!r}"
        return existing + [tool], None

    @staticmethod
    def _merge_scheduler_cron(
        existing: list, item: Any
    ) -> tuple[list | None, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "scheduler_cron item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"scheduler_cron: duplicate name {name!r}"
        return existing + [item], None

    async def _append_blacklist_entry(
        self,
        item: Any,
        validate_value: Any,
        SettingsValidationError: type,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {"ok": False, "error": "safety_blacklist item: values must be an object"}
        domain = item.get("domain")
        tool = item.get("tool")
        if not isinstance(domain, str) or not domain:
            return {"ok": False, "error": "safety_blacklist item: domain must be a non-empty string"}
        if not isinstance(tool, str) or not tool:
            return {"ok": False, "error": "safety_blacklist item: tool must be a non-empty string"}

        try:
            existing = await self._settings_store.get_setting("safety_blacklist")
        except Exception:
            existing = None

        existing_dict: dict = existing if isinstance(existing, dict) else {}
        domain_list: list = list(existing_dict.get(domain, []))

        if tool in domain_list:
            return {"ok": False, "error": f"safety_blacklist[{domain!r}]: duplicate tool {tool!r}"}

        domain_list.append(tool)
        candidate = {**existing_dict, domain: domain_list}

        try:
            cleaned = validate_value("safety_blacklist", candidate)
        except SettingsValidationError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            await self._settings_store.set_setting("safety_blacklist", cleaned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings_append set_setting (safety_blacklist) failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

    async def _append_admin_user(self, item: Any) -> dict[str, Any]:
        """Append a user to safety_permissions.admin_users, preserving other fields."""
        from breadmind.sdui.settings_schema import (
            SettingsValidationError,
            validate_value,
        )

        if not isinstance(item, dict):
            return {"ok": False, "error": "safety_permissions_admin_users: values must be an object"}
        user = item.get("user")
        if not isinstance(user, str) or not user:
            return {"ok": False, "error": "safety_permissions_admin_users: user must be a non-empty string"}

        try:
            existing = await self._settings_store.get_setting("safety_permissions")
        except Exception:
            existing = None

        existing_perms: dict = existing if isinstance(existing, dict) else {}
        admin_users: list = list(existing_perms.get("admin_users", []))

        if user in admin_users:
            return {"ok": False, "error": f"safety_permissions.admin_users: duplicate user {user!r}"}

        admin_users.append(user)
        candidate = {**existing_perms, "admin_users": admin_users}

        try:
            cleaned = validate_value("safety_permissions", candidate)
        except SettingsValidationError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            await self._settings_store.set_setting("safety_permissions", cleaned)
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings_append set_setting (safety_permissions) failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "persisted": True, "refresh_view": "settings_view"}
