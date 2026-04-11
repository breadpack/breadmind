"""Action handler: processes user actions from the SDUI renderer.

Action message shape:
    {"kind": "intervention", "flow_id": ..., "step_id": ..., "value": ...}
    {"kind": "chat_input", "session_id": ..., "values": {"text": ...}}
    {"kind": "view_request", "view_key": ..., "params": ...}  # handled in ws route directly
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Awaitable, Callable
from uuid import UUID

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)

# Vault credential ID: alphanumeric plus _:.@-/ up to 128 chars
_VAULT_ID_RE = re.compile(r"^[A-Za-z0-9_:.@\-/]{1,128}$")
_MAX_VAULT_VALUE_LEN = 64 * 1024

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
        event_bus: Any = None,
        settings_service: Any = None,
    ) -> None:
        self._bus = bus
        self._message_handler = message_handler
        self._working_memory = working_memory
        self._settings_store = settings_store
        self._credential_vault = credential_vault
        self._event_bus = event_bus

        if settings_service is None and settings_store is not None:
            try:
                from breadmind.settings.reload_registry import SettingsReloadRegistry
                from breadmind.settings.service import SettingsService

                settings_service = SettingsService(
                    store=settings_store,
                    vault=credential_vault,
                    audit_sink=self._record_audit,
                    reload_registry=SettingsReloadRegistry(),
                    event_bus=event_bus,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ActionHandler: failed to construct SettingsService: %s", exc
                )
                settings_service = None
        self._settings_service = settings_service

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
        if kind == "credential_store":
            return await self._credential_store(action, user_id)
        if kind == "credential_delete":
            return await self._credential_delete(action, user_id)
        if kind == "settings_update_item":
            return await self._settings_update_item(action, user_id)
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
            await self._record_audit(
                "settings_write",
                key,
                user_id,
                self._audit_summary_settings_write(key, cleaned),
            )
            return {
                "ok": True,
                "persisted": True,
                "restart_required": requires_restart(key),
                "refresh_view": "settings_view",
            }

        if self._settings_store is None:
            return {"ok": False, "error": "settings_store not configured"}

        # Dict-shape merge semantics: existing + new overrides.
        try:
            existing = await self._settings_store.get_setting(key)
        except Exception:
            existing = None
        if isinstance(existing, dict) and isinstance(cleaned, dict):
            merged = {**existing, **cleaned}
        else:
            merged = cleaned

        # Delegate the validated+merged value to SettingsService so the
        # SETTINGS_CHANGED event, audit log, and reload registry fire
        # through a single pipeline.
        if self._settings_service is not None:
            result = await self._settings_service.set(
                key, merged, actor=f"user:{user_id}"
            )
            if not result.ok:
                return {"ok": False, "error": result.error or "set failed"}
            return {
                "ok": True,
                "persisted": result.persisted,
                "restart_required": result.restart_required,
                "refresh_view": "settings_view",
            }

        # Fallback: no SettingsService (e.g. construction failed).
        try:
            await self._settings_store.set_setting(key, merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings_write set_setting failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        await self._record_audit(
            "settings_write",
            key,
            user_id,
            self._audit_summary_settings_write(key, cleaned),
        )
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
    # Audit log
    # ------------------------------------------------------------------

    _AUDIT_KEY = "sdui_audit_log"
    _AUDIT_MAX = 200
    _AUDIT_DISPLAY = 30

    async def _record_audit(
        self,
        action_kind: str | None = None,
        key: str | None = None,
        user_id: str | None = None,
        summary: str | None = None,
        *,
        kind: str | None = None,
        actor: str | None = None,
        old_preview: Any = None,
        new_preview: Any = None,
    ) -> int | None:
        """Append an entry to the sdui_audit_log capped list.

        Accepts both the legacy positional shape
        ``(action_kind, key, user_id, summary)`` used by existing UI paths
        AND the keyword-only shape ``(kind=, key=, actor=, old_preview=,
        new_preview=)`` used by :class:`SettingsService`.

        Never logs sensitive values. Failures are swallowed so audit errors
        never propagate to the caller. Returns the new audit log length on
        success or ``None`` when the store is unavailable / write failed.
        """
        # Normalise compat args: SettingsService passes ``kind=`` and
        # ``actor=``; legacy callers pass the first four as positionals.
        if action_kind is None and kind is not None:
            action_kind = kind
        if actor is None and user_id is not None:
            actor = f"user:{user_id}"
        # Derive a summary for new-style callers if none was supplied. Use
        # the legacy ``_audit_summary_*`` helpers so the audit log entries
        # produced by the new delegation path are byte-compatible with the
        # pre-refactor shape (the UI and existing tests assert on these
        # exact substrings).
        if summary is None:
            if action_kind == "settings_write" and key is not None:
                summary = self._audit_summary_settings_write(key, new_preview)
            elif action_kind == "settings_append" and key is not None:
                summary = self._audit_summary_settings_append(key, new_preview)
            elif action_kind == "settings_update_item" and key is not None:
                summary = self._audit_summary_settings_update_item(key, "")
            elif action_kind == "credential_store":
                summary = "stored"
            elif action_kind == "credential_delete":
                summary = "deleted"
            else:
                summary = action_kind or ""

        if self._settings_store is None:
            return None
        try:
            existing = await self._settings_store.get_setting(self._AUDIT_KEY)
        except Exception:  # noqa: BLE001
            existing = []
        if not isinstance(existing, list):
            existing = []

        # Preserve legacy ``user`` field: for new-style callers the actor is
        # already of the form ``user:<id>`` — strip the prefix so the UI
        # column continues to show raw user ids.
        user_display = user_id
        if user_display is None and isinstance(actor, str):
            user_display = actor.split(":", 1)[1] if actor.startswith("user:") else actor

        entry = {
            "ts": time.time(),
            "action": action_kind,
            "key": key,
            "user": user_display,
            "summary": (summary or "")[:200],
        }
        capped = (existing + [entry])[-self._AUDIT_MAX:]

        try:
            await self._settings_store.set_setting(self._AUDIT_KEY, capped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_record_audit: failed to persist audit log: %s", exc)
            return None
        return len(capped)

    # ------------------------------------------------------------------
    # Audit summary builders (no sensitive values may appear)
    # ------------------------------------------------------------------

    @staticmethod
    def _audit_summary_settings_write(key: str, cleaned: Any) -> str:
        """Build a safe summary for settings_write."""
        if key.startswith("apikey:"):
            name = key[len("apikey:"):]
            return f"key=apikey:{name} (vault)"
        if isinstance(cleaned, dict):
            fields = list(cleaned.keys())
            return f"{len(fields)} field(s) updated: {', '.join(fields)}"
        return "1 field(s) updated"

    @staticmethod
    def _audit_summary_settings_append(key: str, item: Any) -> str:
        """Build a safe summary for settings_append."""
        if isinstance(item, dict):
            name = item.get("name") or item.get("tool") or item.get("user")
            if name:
                return f"appended {key} item: {name}"
        return f"appended {key} item"

    @staticmethod
    def _audit_summary_settings_update_item(key: str, match_value: str) -> str:
        """Build a safe summary for settings_update_item."""
        return f"updated {key} item: {match_value}"

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

        audit_summary = self._audit_summary_settings_append(key, item)

        # ------------------------------------------------------------------
        # Dict-shaped keys: merge locally then delegate via SettingsService.set
        # ------------------------------------------------------------------
        if key == "safety_permissions_admin_users":
            merged_dict, err = await self._build_admin_users_candidate(item)
            if err is not None:
                return {"ok": False, "error": err}
            if self._settings_service is None:
                return await self._append_admin_user(item)  # fallback
            result = await self._settings_service.set(
                "safety_permissions",
                merged_dict,
                actor=f"user:{user_id}",
                audit_summary=audit_summary,
            )
            if not result.ok:
                return {"ok": False, "error": result.error or "set failed"}
            # Override the auto-recorded audit entry key so the UI sees the
            # legacy ``safety_permissions_admin_users`` action key rather
            # than the underlying ``safety_permissions`` storage key.
            await self._rewrite_last_audit(action_key="settings_append", key=key)
            return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

        if key == "safety_blacklist":
            merged_dict, err = await self._build_blacklist_candidate(item)
            if err is not None:
                return {"ok": False, "error": err}
            if self._settings_service is None:
                return await self._append_blacklist_entry(
                    item, validate_value, SettingsValidationError
                )
            result = await self._settings_service.set(
                "safety_blacklist",
                merged_dict,
                actor=f"user:{user_id}",
                audit_summary=audit_summary,
            )
            if not result.ok:
                return {"ok": False, "error": result.error or "set failed"}
            await self._rewrite_last_audit(action_key="settings_append", key=key)
            return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

        # ------------------------------------------------------------------
        # List-shaped keys: run duplicate/validation pre-checks, then delegate
        # via SettingsService.append so hot-reload subscribers fire.
        # ------------------------------------------------------------------
        try:
            existing = await self._settings_store.get_setting(key)
        except Exception:
            existing = None

        existing_list: list = existing if isinstance(existing, list) else []

        if key == "mcp_servers":
            coerced_item, err = self._prepare_mcp_server_item(existing_list, item)
        elif key == "skill_markets":
            coerced_item, err = self._prepare_skill_market_item(existing_list, item)
        elif key == "safety_approval":
            coerced_item, err = self._prepare_safety_approval_item(existing_list, item)
        elif key == "scheduler_cron":
            coerced_item, err = self._prepare_scheduler_cron_item(existing_list, item)
        else:
            return {"ok": False, "error": f"key not allowed for settings_append: {key}"}

        if err is not None:
            return {"ok": False, "error": err}

        if self._settings_service is None:
            # Fallback path for handlers constructed without a service.
            try:
                cleaned = validate_value(key, existing_list + [coerced_item])
            except SettingsValidationError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                await self._settings_store.set_setting(key, cleaned)
            except Exception as exc:  # noqa: BLE001
                logger.warning("settings_append set_setting failed: %s", exc)
                return {"ok": False, "error": str(exc)}
            await self._record_audit(
                "settings_append", key, user_id, audit_summary,
            )
            return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

        result = await self._settings_service.append(
            key, coerced_item, actor=f"user:{user_id}", audit_summary=audit_summary,
        )
        if not result.ok:
            return {"ok": False, "error": result.error or "append failed"}
        return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

    async def _rewrite_last_audit(self, *, action_key: str, key: str) -> None:
        """Rewrite the most recent audit entry's action/key fields in place.

        Used when a translator delegated a dict-shaped setting through
        ``SettingsService.set`` but wants the audit log to show the original
        SDUI action name (e.g. ``settings_append`` targeting
        ``safety_permissions_admin_users``) rather than the storage key
        (``safety_permissions``).
        """
        if self._settings_store is None:
            return
        try:
            existing = await self._settings_store.get_setting(self._AUDIT_KEY)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(existing, list) or not existing:
            return
        last = dict(existing[-1])
        last["action"] = action_key
        last["key"] = key
        new_log = existing[:-1] + [last]
        try:
            await self._settings_store.set_setting(self._AUDIT_KEY, new_log)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Vault credential actions (admin-only; no bootstrap exception)
    # ------------------------------------------------------------------

    async def _credential_store(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Store or rotate a credential in the vault."""
        if not await self._is_admin(user_id):
            return {"ok": False, "error": "permission denied: admin only"}

        if self._credential_vault is None:
            return {"ok": False, "error": "credential vault not configured"}

        # SDUI form widgets place all field values inside ``values``; programmatic
        # callers may pass them at the top level. Accept both shapes so the same
        # action handler works for both.
        values = action.get("values") if isinstance(action.get("values"), dict) else {}
        credential_id = action.get("credential_id") or values.get("credential_id")
        if not isinstance(credential_id, str) or not credential_id:
            return {"ok": False, "error": "credential_id must be a non-empty string"}
        if not _VAULT_ID_RE.match(credential_id):
            return {
                "ok": False,
                "error": (
                    "credential_id invalid: max 128 chars, "
                    "allowed characters: [A-Za-z0-9_:.@\\-/]"
                ),
            }

        value = action.get("value") if "value" in action else values.get("value")
        if not isinstance(value, str) or not value:
            return {"ok": False, "error": "value must be a non-empty string"}
        if len(value) > _MAX_VAULT_VALUE_LEN:
            return {"ok": False, "error": f"value exceeds maximum size of {_MAX_VAULT_VALUE_LEN} bytes"}

        # action.metadata takes precedence; fall back to values.metadata; then description field.
        if "metadata" in action:
            metadata = action.get("metadata")
        elif "metadata" in values:
            metadata = values.get("metadata")
        else:
            # Build metadata from the optional description field in the form values.
            description = values.get("description")
            if isinstance(description, str) and description.strip():
                metadata = {"description": description.strip()}
            else:
                metadata = None

        if metadata is not None and not isinstance(metadata, dict):
            return {"ok": False, "error": "metadata must be a dict if provided"}

        if self._settings_service is not None:
            result = await self._settings_service.store_vault_credential(
                credential_id,
                value,
                metadata=metadata,
                actor=f"user:{user_id}",
                audit_key=f"vault:{credential_id}",
                audit_summary="stored",
            )
            if not result.ok:
                logger.warning(
                    "credential_store delegation failed for %s: %s",
                    credential_id,
                    result.error,
                )
                return {"ok": False, "error": result.error or "credential_store failed"}
            logger.info("credential_store: stored credential %s", credential_id)
            return {
                "ok": True,
                "persisted": result.persisted,
                "credential_id": credential_id,
                "refresh_view": "settings_view",
            }

        # Fallback: no SettingsService available.
        try:
            await self._credential_vault.store(credential_id, value, metadata)
        except Exception as exc:  # noqa: BLE001
            logger.warning("credential_store vault.store failed for %s: %s", credential_id, exc)
            return {"ok": False, "error": str(exc)}

        logger.info("credential_store: stored credential %s", credential_id)
        await self._record_audit(
            "credential_store",
            f"vault:{credential_id}",
            user_id,
            "stored",
        )
        return {
            "ok": True,
            "persisted": True,
            "credential_id": credential_id,
            "refresh_view": "settings_view",
        }

    async def _credential_delete(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Delete a credential from the vault."""
        if not await self._is_admin(user_id):
            return {"ok": False, "error": "permission denied: admin only"}

        if self._credential_vault is None:
            return {"ok": False, "error": "credential vault not configured"}

        values = action.get("values") if isinstance(action.get("values"), dict) else {}
        credential_id = action.get("credential_id") or values.get("credential_id")
        if not isinstance(credential_id, str) or not credential_id:
            return {"ok": False, "error": "credential_id must be a non-empty string"}
        if not _VAULT_ID_RE.match(credential_id):
            return {
                "ok": False,
                "error": (
                    "credential_id invalid: max 128 chars, "
                    "allowed characters: [A-Za-z0-9_:.@\\-/]"
                ),
            }

        if self._settings_service is not None:
            result = await self._settings_service.delete_vault_credential(
                credential_id,
                actor=f"user:{user_id}",
                audit_key=f"vault:{credential_id}",
                audit_summary="deleted",
            )
            if not result.ok:
                if result.error == "credential not found":
                    logger.warning(
                        "credential_delete: credential not found: %s", credential_id
                    )
                return {"ok": False, "error": result.error or "credential_delete failed"}
            logger.info("credential_delete: deleted credential %s", credential_id)
            return {
                "ok": True,
                "persisted": result.persisted,
                "credential_id": credential_id,
                "refresh_view": "settings_view",
            }

        # Fallback: no SettingsService available.
        try:
            deleted = await self._credential_vault.delete(credential_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("credential_delete vault.delete failed for %s: %s", credential_id, exc)
            return {"ok": False, "error": str(exc)}

        if not deleted:
            logger.warning("credential_delete: credential not found: %s", credential_id)
            return {"ok": False, "error": "credential not found"}

        logger.info("credential_delete: deleted credential %s", credential_id)
        await self._record_audit(
            "credential_delete",
            f"vault:{credential_id}",
            user_id,
            "deleted",
        )
        return {
            "ok": True,
            "persisted": True,
            "credential_id": credential_id,
            "refresh_view": "settings_view",
        }

    # ------------------------------------------------------------------
    # Allowed keys for settings_update_item (list[dict] keys only)
    # ------------------------------------------------------------------
    _UPDATE_ITEM_ALLOWED_KEYS = frozenset(
        {
            "mcp_servers",
            "skill_markets",
            "scheduler_cron",
        }
    )

    async def _settings_update_item(
        self, action: dict[str, Any], user_id: str
    ) -> dict[str, Any]:
        """Replace a single item in a list-shaped setting identified by a match field.

        Action shape::
            {
                "kind": "settings_update_item",
                "key": "mcp_servers",
                "match_field": "name",
                "match_value": "github",
                "values": { <new item fields> }
            }

        For ``mcp_servers``: args/env/enabled string values are parsed before
        merging using the same helpers as ``_settings_append``.
        """
        from breadmind.sdui.settings_schema import (
            SettingsValidationError,
            validate_value,
        )

        key = action.get("key")
        if key not in self._UPDATE_ITEM_ALLOWED_KEYS:
            return {"ok": False, "error": f"key not allowed for settings_update_item: {key}"}

        if self._settings_store is None:
            return {"ok": False, "error": "settings_store not configured"}

        match_field = action.get("match_field")
        match_value = action.get("match_value")
        values = action.get("values")

        if not isinstance(match_field, str) or not match_field:
            return {"ok": False, "error": "match_field must be a non-empty string"}
        if not isinstance(match_value, str) or not match_value:
            return {"ok": False, "error": "match_value must be a non-empty string"}
        if not isinstance(values, dict):
            return {"ok": False, "error": "values must be an object"}

        try:
            existing = await self._settings_store.get_setting(key)
        except Exception:
            existing = None

        existing_list: list = existing if isinstance(existing, list) else []

        # Find the item to replace.
        idx = next(
            (i for i, item in enumerate(existing_list) if item.get(match_field) == match_value),
            None,
        )
        if idx is None:
            return {"ok": False, "error": f"{key}: item with {match_field}={match_value!r} not found"}

        # For mcp_servers: parse string args/env/enabled before building the new item.
        if key == "mcp_servers":
            parsed_values, err = self._parse_mcp_server_values(values)
            if err is not None:
                return {"ok": False, "error": err}
        else:
            parsed_values = dict(values)

        audit_summary = self._audit_summary_settings_update_item(key, match_value)

        if self._settings_service is None:
            # Fallback path for handlers constructed without a service.
            original_item = existing_list[idx]
            new_item = {**original_item, **parsed_values}
            new_list = existing_list[:idx] + [new_item] + existing_list[idx + 1:]
            try:
                cleaned = validate_value(key, new_list)
            except SettingsValidationError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                await self._settings_store.set_setting(key, cleaned)
            except Exception as exc:  # noqa: BLE001
                logger.warning("settings_update_item set_setting failed: %s", exc)
                return {"ok": False, "error": str(exc)}
            await self._record_audit(
                "settings_update_item", key, user_id, audit_summary,
            )
            return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

        result = await self._settings_service.update_item(
            key,
            match_field=match_field,
            match_value=match_value,
            patch=parsed_values,
            actor=f"user:{user_id}",
            audit_summary=audit_summary,
        )
        if not result.ok:
            # Translate SettingsService's generic "no matching item" into the
            # existing SDUI error string that tests assert on.
            err = result.error or "update_item failed"
            if "no matching item" in err:
                err = f"{key}: item with {match_field}={match_value!r} not found"
            return {"ok": False, "error": err}
        return {"ok": True, "persisted": True, "refresh_view": "settings_view"}

    # ------------------------------------------------------------------
    # Per-key merge helpers (return (merged_candidate, error_str|None))
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_args_text(s: Any) -> list[str]:
        """Parse a multiline args string into list[str].

        Each non-empty stripped line becomes one argument.
        If ``s`` is already a list, it is returned as-is.
        """
        if isinstance(s, list):
            return s
        if not isinstance(s, str):
            return []
        return [line.strip() for line in s.splitlines() if line.strip()]

    @staticmethod
    def _parse_env_text(s: Any) -> tuple[dict[str, str] | None, str | None]:
        """Parse a multiline env string into dict[str, str].

        Each non-empty stripped line must be in ``KEY=VALUE`` format.
        The value part may itself contain ``=`` characters.
        If ``s`` is already a dict, it is returned as-is.
        Returns ``(parsed_dict, None)`` on success or ``(None, error_str)`` on failure.
        """
        if isinstance(s, dict):
            return s, None
        if not isinstance(s, str):
            return {}, None
        out: dict[str, str] = {}
        for line in s.splitlines():
            line = line.strip()
            if not line:
                continue
            if "=" not in line:
                return None, f"env line is missing '=': {line!r}"
            key, _, value = line.partition("=")
            out[key.strip()] = value
        return out, None

    @staticmethod
    def _parse_mcp_server_values(values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """Parse args/env/enabled string fields in a mcp_servers item dict.

        Non-string args/env values are passed through unchanged so existing callers
        that pass native list/dict continue to work.
        Returns ``(parsed_dict, None)`` on success or ``(None, error_str)`` on failure.
        """
        from breadmind.sdui.settings_schema import SettingsValidationError, _coerce_bool

        result = dict(values)

        # Parse args.
        if isinstance(result.get("args"), str):
            result["args"] = ActionHandler._parse_args_text(result["args"])

        # Parse env.
        if isinstance(result.get("env"), str):
            parsed_env, err = ActionHandler._parse_env_text(result["env"])
            if err is not None:
                return None, err
            result["env"] = parsed_env

        # Coerce enabled string.
        if isinstance(result.get("enabled"), str):
            try:
                result["enabled"] = _coerce_bool(result["enabled"], "enabled")
            except SettingsValidationError as exc:
                return None, str(exc)

        return result, None

    # ------------------------------------------------------------------
    # Per-key item preparation helpers (return (coerced_item, error|None)).
    # These preserve the pre-check error strings that SDUI tests assert on,
    # so they must stay in the translator (SettingsService does not see the
    # raw incoming item before append).
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_mcp_server_item(
        existing: list, item: Any
    ) -> tuple[Any, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "mcp_servers item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"mcp_servers: duplicate name {name!r}"
        parsed_item, err = ActionHandler._parse_mcp_server_values(item)
        if err is not None:
            return None, err
        return parsed_item, None

    @staticmethod
    def _prepare_skill_market_item(
        existing: list, item: Any
    ) -> tuple[Any, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "skill_markets item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"skill_markets: duplicate name {name!r}"
        return item, None

    @staticmethod
    def _prepare_safety_approval_item(
        existing: list, item: Any
    ) -> tuple[Any, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object with a 'tool' field"
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool:
            return None, "safety_approval item: tool must be a non-empty string"
        if tool in existing:
            return None, f"safety_approval: duplicate tool {tool!r}"
        return tool, None

    @staticmethod
    def _prepare_scheduler_cron_item(
        existing: list, item: Any
    ) -> tuple[Any, str | None]:
        if not isinstance(item, dict):
            return None, "values must be an object"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None, "scheduler_cron item: name must be a non-empty string"
        if any(s.get("name") == name for s in existing):
            return None, f"scheduler_cron: duplicate name {name!r}"
        return item, None

    async def _build_blacklist_candidate(
        self, item: Any
    ) -> tuple[dict | None, str | None]:
        """Pre-check and build the full safety_blacklist dict for delegation."""
        if not isinstance(item, dict):
            return None, "safety_blacklist item: values must be an object"
        domain = item.get("domain")
        tool = item.get("tool")
        if not isinstance(domain, str) or not domain:
            return None, "safety_blacklist item: domain must be a non-empty string"
        if not isinstance(tool, str) or not tool:
            return None, "safety_blacklist item: tool must be a non-empty string"

        try:
            existing = await self._settings_store.get_setting("safety_blacklist")
        except Exception:  # noqa: BLE001
            existing = None

        existing_dict: dict = existing if isinstance(existing, dict) else {}
        domain_list: list = list(existing_dict.get(domain, []))

        if tool in domain_list:
            return None, f"safety_blacklist[{domain!r}]: duplicate tool {tool!r}"

        domain_list.append(tool)
        return {**existing_dict, domain: domain_list}, None

    async def _build_admin_users_candidate(
        self, item: Any
    ) -> tuple[dict | None, str | None]:
        """Pre-check and build the full safety_permissions dict for delegation."""
        if not isinstance(item, dict):
            return None, "safety_permissions_admin_users: values must be an object"
        user = item.get("user")
        if not isinstance(user, str) or not user:
            return None, "safety_permissions_admin_users: user must be a non-empty string"

        try:
            existing = await self._settings_store.get_setting("safety_permissions")
        except Exception:  # noqa: BLE001
            existing = None

        existing_perms: dict = existing if isinstance(existing, dict) else {}
        admin_users: list = list(existing_perms.get("admin_users", []))

        if user in admin_users:
            return None, f"safety_permissions.admin_users: duplicate user {user!r}"

        admin_users.append(user)
        return {**existing_perms, "admin_users": admin_users}, None

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
        # Parse string args/env/enabled when the form submits multiline text.
        parsed_item, err = ActionHandler._parse_mcp_server_values(item)
        if err is not None:
            return None, err
        return existing + [parsed_item], None

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
