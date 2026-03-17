"""Bidirectional sync engine with last-writer-wins conflict resolution."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConflictRecord:
    entity_table: str
    entity_id: str
    local_data: dict
    remote_data: dict
    resolution: str  # "local_wins" | "remote_wins"


class SyncEngine:
    """Coordinates bidirectional sync between local and remote adapters."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    async def resolve_conflict(
        self,
        entity_table: str,
        entity_id: str,
        local_data: dict,
        remote_data: dict,
    ) -> str:
        """Resolve a sync conflict using last-writer-wins.

        Compares updated_at (or created_at) timestamps.
        Returns "local_wins" or "remote_wins".
        Logs conflict to sync_conflicts table.
        """
        local_time = self._get_timestamp(local_data)
        remote_time = self._get_timestamp(remote_data)

        resolution = "local_wins" if local_time >= remote_time else "remote_wins"

        # Log conflict for audit trail
        await self._log_conflict(ConflictRecord(
            entity_table=entity_table,
            entity_id=entity_id,
            local_data=local_data,
            remote_data=remote_data,
            resolution=resolution,
        ))

        logger.info(
            "Sync conflict resolved: %s/%s → %s (local=%s, remote=%s)",
            entity_table, entity_id, resolution, local_time, remote_time,
        )
        return resolution

    async def sync_adapter(
        self,
        local_adapter: Any,
        remote_adapter: Any,
        user_id: str,
        since: datetime | None = None,
    ) -> dict:
        """Run bidirectional sync between local and remote adapters.

        Returns summary dict with counts of created/updated/conflicts.
        """
        stats = {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": []}

        # Pull remote changes
        try:
            remote_items = await remote_adapter.list_items(
                filters={"user_id": user_id}, limit=100
            )
        except Exception as e:
            stats["errors"].append(f"Remote fetch failed: {e}")
            return stats

        for remote_item in remote_items:
            source_id = getattr(remote_item, "source_id", None) or getattr(remote_item, "id", "")
            try:
                local_item = await local_adapter.get_item(source_id)
            except Exception:
                local_item = None

            if local_item is None:
                # New remote item → pull
                try:
                    await local_adapter.create_item(remote_item)
                    stats["pulled"] += 1
                except Exception as e:
                    stats["errors"].append(f"Pull create failed: {e}")
            else:
                # Both exist → check conflict
                local_data = self._to_dict(local_item)
                remote_data = self._to_dict(remote_item)

                if local_data != remote_data:
                    resolution = await self.resolve_conflict(
                        entity_table=local_adapter.domain,
                        entity_id=source_id,
                        local_data=local_data,
                        remote_data=remote_data,
                    )
                    stats["conflicts"] += 1

                    if resolution == "remote_wins":
                        try:
                            await local_adapter.update_item(source_id, remote_data)
                            stats["pulled"] += 1
                        except Exception as e:
                            stats["errors"].append(f"Pull update failed: {e}")

        return stats

    async def _log_conflict(self, record: ConflictRecord) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO sync_conflicts (entity_table, entity_id, local_data, remote_data, resolution)
                       VALUES ($1, $2::uuid, $3::jsonb, $4::jsonb, $5)""",
                    record.entity_table,
                    record.entity_id,
                    json.dumps(record.local_data, default=str),
                    json.dumps(record.remote_data, default=str),
                    record.resolution,
                )
        except Exception:
            logger.exception("Failed to log sync conflict")

    @staticmethod
    def _get_timestamp(data: dict) -> datetime:
        for key in ("updated_at", "created_at", "timestamp"):
            val = data.get(key)
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    continue
        return datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _to_dict(obj: Any) -> dict:
        if hasattr(obj, "__dataclass_fields__"):
            from dataclasses import asdict
            return asdict(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return dict(obj) if isinstance(obj, dict) else {}
