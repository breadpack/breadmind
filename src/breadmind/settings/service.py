"""Facade for runtime settings read/write with validation, audit, and hot reload.

``SettingsService`` is the one object that owns the settings write pipeline:
validate → authorize → persist → audit → dispatch reload subscribers. Both the
SDUI ``ActionHandler`` and the built-in agent tools go through it so every
write path produces the same side effects.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from breadmind.core.events import EventBus, EventType
from breadmind.sdui import settings_schema
from breadmind.settings.reload_registry import SettingsReloadRegistry

AuditSink = Callable[..., Awaitable[int | None]]


@dataclass
class SetResult:
    ok: bool
    operation: str
    key: str
    persisted: bool = False
    hot_reloaded: bool = False
    restart_required: bool = False
    reload_errors: dict[str, str] = field(default_factory=dict)
    audit_id: int | None = None
    pending_approval_id: str | None = None
    error: str | None = None

    def summary(self) -> str:
        if self.pending_approval_id is not None:
            return (
                f"PENDING: approval required for key={self.key}. "
                f"approval_id={self.pending_approval_id}. Ask the user to confirm."
            )
        if not self.ok:
            return f"ERROR: {self.error or 'unknown error'}"
        parts = [
            "OK",
            f"key={self.key}",
            f"operation={self.operation}",
            f"hot_reloaded={str(self.hot_reloaded).lower()}",
            f"restart_required={str(self.restart_required).lower()}",
        ]
        if self.audit_id is not None:
            parts.append(f"audit_id={self.audit_id}")
        if self.reload_errors:
            parts.append(f"reload_errors={list(self.reload_errors.keys())}")
        return ". ".join(parts[:1]) + ". " + ", ".join(parts[1:])


class SettingsService:
    def __init__(
        self,
        *,
        store: Any,
        vault: Any,
        audit_sink: AuditSink,
        reload_registry: SettingsReloadRegistry,
        event_bus: EventBus | None = None,
    ) -> None:
        self._store = store
        self._vault = vault
        self._audit_sink = audit_sink
        self._registry = reload_registry
        self._bus = event_bus
        self._key_locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        # ``setdefault`` is atomic for dict operations in CPython, so two
        # coroutines racing for a first-time key always end up with the same
        # lock instance even if a future edit sneaks an ``await`` into this
        # path.
        return self._key_locks.setdefault(key, asyncio.Lock())

    def _build_event_payload(
        self,
        *,
        key: str,
        operation: str,
        old: Any,
        new: Any,
        actor: str,
        audit_id: int | None,
    ) -> dict[str, Any] | None:
        """Build the SETTINGS_CHANGED payload, masking credential plaintext.

        Returns ``None`` when no event bus is configured — callers can then
        skip the emit entirely. Credential keys always get ``old=new=None``
        as defense in depth, even if a caller forgot to mask.
        """
        if self._bus is None:
            return None
        if settings_schema.is_credential_key(key):
            old_payload = None
            new_payload = None
        else:
            old_payload = old
            new_payload = new
        return {
            "key": key,
            "operation": operation,
            "old": old_payload,
            "new": new_payload,
            "actor": actor,
            "audit_id": audit_id,
        }

    async def _emit_payload(self, payload: dict[str, Any] | None) -> None:
        """Publish a prepared SETTINGS_CHANGED payload.

        Kept separate from :meth:`_build_event_payload` so callers can build
        the payload *inside* the per-key lock (snapshot of pre/post state)
        but run the actual ``async_emit`` *outside* the lock, avoiding a
        deadlock if a subscriber writes back into ``SettingsService`` for
        the same key (``asyncio.Lock`` is non-reentrant).
        """
        if payload is None or self._bus is None:
            return
        await self._bus.async_emit(EventType.SETTINGS_CHANGED.value, payload)

    async def get(self, key: str) -> Any:
        if settings_schema.is_credential_key(key):
            return "●●●●"
        return await self._store.get_setting(key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        actor: str,
        audit_summary: str | None = None,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(
                ok=False,
                operation="set",
                key=key,
                error=f"key '{key}' is not allowed",
            )
        try:
            normalized = settings_schema.validate_value(key, value)
        except settings_schema.SettingsValidationError as exc:
            return SetResult(
                ok=False,
                operation="set",
                key=key,
                error=f"validation failed — {exc}",
            )

        async with self._lock(key):
            old = await self._store.get_setting(key)
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_write",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="set", old=old, new=normalized
            )
            event_payload = self._build_event_payload(
                key=key, operation="set", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)

        return SetResult(
            ok=True,
            operation="set",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def append(
        self,
        key: str,
        item: Any,
        *,
        actor: str,
        audit_summary: str | None = None,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="append", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="append", key=key,
                    error=f"key '{key}' is not a list",
                )
            merged = [*old, item]
            try:
                normalized = settings_schema.validate_value(key, merged)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="append", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_append",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="append", old=old, new=normalized
            )
            event_payload = self._build_event_payload(
                key=key, operation="append", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)

        return SetResult(
            ok=True,
            operation="append",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def update_item(
        self,
        key: str,
        *,
        match_field: str,
        match_value: Any,
        patch: dict[str, Any],
        actor: str,
        audit_summary: str | None = None,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="update_item", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"key '{key}' is not a list",
                )
            idx = next(
                (i for i, it in enumerate(old)
                 if isinstance(it, dict) and it.get(match_field) == match_value),
                None,
            )
            if idx is None:
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"no matching item for {match_field}={match_value}",
                )
            new_list = [dict(it) for it in old]
            new_list[idx] = {**new_list[idx], **patch}
            try:
                normalized = settings_schema.validate_value(key, new_list)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_update_item",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="update_item", old=old, new=normalized
            )
            event_payload = self._build_event_payload(
                key=key, operation="update_item", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)

        return SetResult(
            ok=True,
            operation="update_item",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def delete_item(
        self,
        key: str,
        *,
        match_field: str,
        match_value: Any,
        actor: str,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="delete_item", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"key '{key}' is not a list",
                )
            new_list = [
                it for it in old
                if not (isinstance(it, dict) and it.get(match_field) == match_value)
            ]
            if len(new_list) == len(old):
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"no matching item for {match_field}={match_value}",
                )
            try:
                normalized = settings_schema.validate_value(key, new_list)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_delete_item",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="delete_item", old=old, new=normalized
            )
            event_payload = self._build_event_payload(
                key=key, operation="delete_item", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)

        return SetResult(
            ok=True,
            operation="delete_item",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def set_credential(
        self,
        key: str,
        value: str,
        *,
        actor: str,
        description: str = "",
        audit_summary: str | None = None,
    ) -> SetResult:
        if not settings_schema.is_credential_key(key):
            return SetResult(
                ok=False,
                operation="credential_store",
                key=key,
                error=f"key '{key}' is not a credential key",
            )
        metadata: dict[str, Any] = {}
        if description:
            metadata["description"] = description

        async with self._lock(key):
            await self._vault.store(key, value, metadata or None)
            audit_id = await self._audit_sink(
                kind="credential_store",
                key=key,
                actor=actor,
                old_preview=None,
                new_preview=None,
                summary=audit_summary,
            )
            # Credentials never carry plaintext through events.
            dispatch = await self._registry.dispatch(
                key=key, operation="credential_store", old=None, new=None
            )
            event_payload = self._build_event_payload(
                key=key, operation="credential_store", old=None, new=None,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)

        return SetResult(
            ok=True,
            operation="credential_store",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def store_vault_credential(
        self,
        vault_id: str,
        value: str,
        *,
        metadata: dict[str, Any] | None,
        actor: str,
        audit_key: str | None = None,
        audit_summary: str | None = None,
    ) -> SetResult:
        """Store a raw vault credential without the ``apikey:`` key check.

        Unlike :meth:`set_credential` this accepts any vault id (e.g.
        ``ssh:prod``) and is intended for the SDUI credential_store action
        path, which uses a separate vault id namespace from whitelisted
        ``apikey:*`` settings. The pipeline still fires audit, reload
        dispatch, and SETTINGS_CHANGED events — but plaintext is never
        passed to any of them.
        """
        async with self._lock(vault_id):
            try:
                await self._vault.store(vault_id, value, metadata)
            except Exception as exc:  # noqa: BLE001
                return SetResult(
                    ok=False, operation="credential_store", key=vault_id,
                    error=str(exc),
                )
            audit_id = await self._audit_sink(
                kind="credential_store",
                key=audit_key or vault_id,
                actor=actor,
                old_preview=None,
                new_preview=None,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=vault_id, operation="credential_store", old=None, new=None,
            )
            event_payload = self._build_event_payload(
                key=vault_id, operation="credential_store", old=None, new=None,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)
        return SetResult(
            ok=True,
            operation="credential_store",
            key=vault_id,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=False,
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def delete_vault_credential(
        self,
        vault_id: str,
        *,
        actor: str,
        audit_key: str | None = None,
        audit_summary: str | None = None,
    ) -> SetResult:
        """Delete a raw vault credential without the ``apikey:`` key check.

        Returns ``ok=False`` with ``error="credential not found"`` when the
        vault reports no such id (matching the legacy SDUI action shape).
        """
        async with self._lock(vault_id):
            try:
                deleted = await self._vault.delete(vault_id)
            except Exception as exc:  # noqa: BLE001
                return SetResult(
                    ok=False, operation="credential_delete", key=vault_id,
                    error=str(exc),
                )
            if not deleted:
                return SetResult(
                    ok=False, operation="credential_delete", key=vault_id,
                    error="credential not found",
                )
            audit_id = await self._audit_sink(
                kind="credential_delete",
                key=audit_key or vault_id,
                actor=actor,
                old_preview=None,
                new_preview=None,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=vault_id, operation="credential_delete", old=None, new=None,
            )
            event_payload = self._build_event_payload(
                key=vault_id, operation="credential_delete", old=None, new=None,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)
        return SetResult(
            ok=True,
            operation="credential_delete",
            key=vault_id,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=False,
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def delete_credential(self, key: str, *, actor: str) -> SetResult:
        if not settings_schema.is_credential_key(key):
            return SetResult(
                ok=False,
                operation="credential_delete",
                key=key,
                error=f"key '{key}' is not a credential key",
            )
        async with self._lock(key):
            await self._vault.delete(key)
            audit_id = await self._audit_sink(
                kind="credential_delete",
                key=key,
                actor=actor,
                old_preview=None,
                new_preview=None,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="credential_delete", old=None, new=None
            )
            event_payload = self._build_event_payload(
                key=key, operation="credential_delete", old=None, new=None,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)
        return SetResult(
            ok=True,
            operation="credential_delete",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )
