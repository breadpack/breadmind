"""Celery Beat schedule generation and the confluence_sync task body.

Runs hourly. One schedule entry per enabled ``connector_configs`` row
with ``connector='confluence'``. The task bootstraps a DB connection
and CredentialVault, constructs a ConfluenceConnector, and runs sync.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Iterable

from breadmind.kb.connectors.base import SyncResult
from breadmind.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

CONFLUENCE_SYNC_TASK: str = "connectors.confluence_sync"
HOURLY_SECONDS: float = 3600.0


def build_beat_schedule(configs: Iterable[Any]) -> dict:
    entries: dict = {}
    for cfg in configs:
        if not getattr(cfg, "enabled", False):
            continue
        if cfg.connector != "confluence":
            continue
        name = f"confluence:{cfg.scope_key}"
        entries[name] = {
            "task": CONFLUENCE_SYNC_TASK,
            "schedule": HOURLY_SECONDS,
            "kwargs": {
                "project_id": str(cfg.project_id),
                "scope_key": cfg.scope_key,
                "base_url": cfg.settings.get("base_url", ""),
                "credentials_ref": cfg.settings.get("credentials_ref", ""),
            },
        }
    return entries


async def _build_confluence_connector(
    *, base_url: str, credentials_ref: str
) -> Any:
    """Factory that wires DB, vault, extractor, and review queue."""
    from breadmind.storage.database import Database
    from breadmind.storage.credential_vault import CredentialVault
    from breadmind.kb.extractor import KnowledgeExtractor
    from breadmind.kb.review_queue import ReviewQueue
    from breadmind.kb.connectors.confluence import ConfluenceConnector

    dsn = os.environ.get("BREADMIND_DSN", "")
    db = Database(dsn)
    await db.connect()
    vault = CredentialVault(db)
    extractor = KnowledgeExtractor(db)
    review_queue = ReviewQueue(db)

    return ConfluenceConnector(
        db=db,
        base_url=base_url,
        credentials_ref=credentials_ref,
        extractor=extractor,
        review_queue=review_queue,
        vault=vault,
    )


async def run_confluence_sync(
    *,
    project_id: str,
    scope_key: str,
    base_url: str,
    credentials_ref: str,
) -> dict:
    conn = await _build_confluence_connector(
        base_url=base_url, credentials_ref=credentials_ref
    )
    cursor = await conn.load_cursor(scope_key)
    result: SyncResult = await conn.sync(
        uuid.UUID(project_id), scope_key, cursor
    )
    return {
        "processed": result.processed,
        "errors": result.errors,
        "new_cursor": result.new_cursor,
    }


@celery_app.task(name=CONFLUENCE_SYNC_TASK, bind=True, acks_late=True)
def confluence_sync_task(
    self, *, project_id: str, scope_key: str, base_url: str,
    credentials_ref: str,
):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_confluence_sync(
            project_id=project_id,
            scope_key=scope_key,
            base_url=base_url,
            credentials_ref=credentials_ref,
        ))
    finally:
        loop.close()


async def reload_beat_schedule_from_db(db: Any) -> None:
    from breadmind.kb.connectors.configs_store import ConnectorConfigsStore
    store = ConnectorConfigsStore(db)
    configs = await store.list(connector="confluence", enabled_only=True)
    celery_app.conf.beat_schedule = build_beat_schedule(configs)
    logger.info(
        "Installed Confluence beat schedule: %d entries",
        len(celery_app.conf.beat_schedule),
    )
