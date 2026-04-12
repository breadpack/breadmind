from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class HookOverride:
    hook_id: str
    source: str | None
    event: str
    type: str  # "python" | "shell"
    tool_pattern: str | None
    priority: int
    enabled: bool
    config_json: dict[str, Any]


class HookOverrideStore:
    """Async access to hook_overrides table. Accepts any asyncpg-like pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_by_event(self, event: str) -> list[HookOverride]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hook_id, source, event, type, tool_pattern, "
                "priority, enabled, config_json "
                "FROM hook_overrides WHERE event = $1 ORDER BY priority DESC",
                event,
            )
        return [self._row_to_override(r) for r in rows]

    async def list_all(self) -> list[HookOverride]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT hook_id, source, event, type, tool_pattern, "
                "priority, enabled, config_json FROM hook_overrides",
            )
        return [self._row_to_override(r) for r in rows]

    async def insert(self, ov: HookOverride) -> None:
        cfg = ov.config_json
        if isinstance(cfg, dict):
            cfg_param = json.dumps(cfg)
        elif isinstance(cfg, str):
            cfg_param = cfg
        else:
            cfg_param = json.dumps(cfg or {})
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO hook_overrides "
                "(hook_id, source, event, type, tool_pattern, priority, enabled, config_json) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
                ov.hook_id, ov.source, ov.event, ov.type,
                ov.tool_pattern, ov.priority, ov.enabled, cfg_param,
            )

    async def delete(self, hook_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM hook_overrides WHERE hook_id = $1", hook_id,
            )

    @staticmethod
    def _row_to_override(r: Any) -> HookOverride:
        def g(k: str) -> Any:
            try:
                return r[k]
            except (KeyError, TypeError):
                return getattr(r, k, None)

        cfg = g("config_json")
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return HookOverride(
            hook_id=g("hook_id"),
            source=g("source"),
            event=g("event"),
            type=g("type"),
            tool_pattern=g("tool_pattern"),
            priority=int(g("priority") or 0),
            enabled=bool(g("enabled")),
            config_json=cfg or {},
        )
