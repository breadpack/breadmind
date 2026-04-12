from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.hooks.chain import HookChain
from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.events import HookEvent
from breadmind.hooks.handler import HookHandler, PythonHook, ShellHook

logger = logging.getLogger(__name__)


@dataclass
class HookRegistry:
    store: Any  # HookOverrideStore-like
    _manifest: dict[str, HookHandler] = field(default_factory=dict)
    _merged: dict[HookEvent, list[HookHandler]] = field(default_factory=dict)

    def add_manifest_hook(self, hook: HookHandler) -> None:
        self._manifest[hook.name] = hook

    def remove_manifest_hooks_by_source(self, plugin_name: str) -> None:
        prefix = f"{plugin_name}:"
        for name in list(self._manifest):
            if name.startswith(prefix):
                del self._manifest[name]

    async def reload(self) -> None:
        """Rebuild merged chains from manifest + DB overrides."""
        try:
            overrides = await self.store.list_all()
        except Exception as e:
            logger.error("Failed to load hook overrides: %s", e)
            overrides = []

        by_name: dict[str, HookOverride] = {ov.hook_id: ov for ov in overrides}
        merged: dict[HookEvent, list[HookHandler]] = {}

        # 1) Manifest hooks (apply DB overrides if matching hook_id)
        for name, hook in self._manifest.items():
            ov = by_name.get(name)
            effective = hook
            if ov is not None:
                if not ov.enabled:
                    continue
                expected_type = hook.__class__.__name__.lower().replace("hook", "")
                if ov.type != expected_type:
                    logger.warning(
                        "DB override for %r tries to change type from %s to %s; ignoring type change",
                        name, hook.__class__.__name__, ov.type,
                    )
                effective = self._apply_override(hook, ov)
            merged.setdefault(hook.event, []).append(effective)

        # 2) DB-only new hooks (hook_id not in manifest)
        for ov in overrides:
            if ov.hook_id in self._manifest:
                continue
            if not ov.enabled:
                continue
            try:
                ev = HookEvent(ov.event)
            except ValueError:
                logger.warning("DB override %r: unknown event %r", ov.hook_id, ov.event)
                continue
            built = self._build_from_override(ov, ev)
            if built is not None:
                merged.setdefault(ev, []).append(built)

        self._merged = merged

    def build_chain(self, event: HookEvent) -> HookChain:
        return HookChain(event=event, handlers=list(self._merged.get(event, [])))

    @staticmethod
    def _apply_override(hook: HookHandler, ov: HookOverride) -> HookHandler:
        new_hook = copy.copy(hook)
        new_hook.priority = ov.priority
        if ov.tool_pattern is not None:
            new_hook.tool_pattern = ov.tool_pattern
        timeout = ov.config_json.get("timeout_sec") if ov.config_json else None
        if timeout is not None:
            new_hook.timeout_sec = float(timeout)
        return new_hook

    @staticmethod
    def _build_from_override(ov: HookOverride, event: HookEvent) -> HookHandler | None:
        cfg = ov.config_json or {}
        if ov.type == "shell":
            command = cfg.get("command", "")
            if not command:
                logger.warning("DB shell hook %r missing command", ov.hook_id)
                return None
            return ShellHook(
                name=ov.hook_id, event=event, command=command,
                priority=ov.priority, tool_pattern=ov.tool_pattern,
                timeout_sec=float(cfg.get("timeout_sec", 10.0)),
                shell=cfg.get("shell", "auto"),
            )
        if ov.type == "python":
            logger.warning(
                "DB-only Python hook %r not supported in Phase 1", ov.hook_id,
            )
            return None
        logger.warning("Unknown override type %r", ov.type)
        return None
