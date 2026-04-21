"""CRUD helpers for the ``connector_configs`` table."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class ConnectorConfigRow:
    id: uuid.UUID
    connector: str
    project_id: uuid.UUID
    scope_key: str
    settings: dict
    enabled: bool


class ConnectorConfigsStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def list(
        self, connector: str | None = None, enabled_only: bool = False
    ) -> list[ConnectorConfigRow]:
        sql = (
            "SELECT id, connector, project_id, scope_key, settings, enabled "
            "FROM connector_configs"
        )
        where: list[str] = []
        args: list[Any] = []
        if connector is not None:
            args.append(connector)
            where.append(f"connector = ${len(args)}")
        if enabled_only:
            where.append("enabled = true")
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = await self._db.fetch(sql, *args)
        return [self._row(r) for r in rows]

    async def register(
        self,
        *,
        connector: str,
        project_id: uuid.UUID,
        scope_key: str,
        settings: dict,
        enabled: bool = True,
    ) -> ConnectorConfigRow:
        row = await self._db.fetchrow(
            """
            INSERT INTO connector_configs (connector, project_id, scope_key, settings, enabled)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (connector, scope_key) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                settings   = EXCLUDED.settings,
                enabled    = EXCLUDED.enabled
            RETURNING id, connector, project_id, scope_key, settings, enabled
            """,
            connector, project_id, scope_key, json.dumps(settings), enabled,
        )
        return self._row(row)

    async def set_enabled(self, config_id: uuid.UUID, enabled: bool) -> None:
        await self._db.execute(
            "UPDATE connector_configs SET enabled = $1 WHERE id = $2",
            enabled, config_id,
        )

    async def delete(self, config_id: uuid.UUID) -> None:
        await self._db.execute(
            "DELETE FROM connector_configs WHERE id = $1",
            config_id,
        )

    @staticmethod
    def _row(r) -> ConnectorConfigRow:
        settings = r["settings"]
        if isinstance(settings, str):
            settings = json.loads(settings)
        return ConnectorConfigRow(
            id=r["id"],
            connector=r["connector"],
            project_id=r["project_id"],
            scope_key=r["scope_key"],
            settings=settings or {},
            enabled=bool(r["enabled"]),
        )
