"""Celery beat schedule registration + task wiring tests."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from breadmind.kb.connectors.schedule import (
    CONFLUENCE_SYNC_TASK,
    build_beat_schedule,
    run_confluence_sync,
)


def test_task_name_is_connectors_confluence_sync():
    assert CONFLUENCE_SYNC_TASK == "connectors.confluence_sync"


def test_build_beat_schedule_one_entry_per_enabled_config():
    configs = [
        MagicMock(
            id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            connector="confluence",
            scope_key="SPACE_A",
            project_id=uuid.UUID("00000000-0000-4000-8000-000000000aaa"),
            settings={"base_url": "https://x", "credentials_ref": "confluence:a"},
            enabled=True,
        ),
        MagicMock(
            id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
            connector="confluence",
            scope_key="SPACE_B",
            project_id=uuid.UUID("00000000-0000-4000-8000-000000000bbb"),
            settings={"base_url": "https://x", "credentials_ref": "confluence:b"},
            enabled=False,
        ),
    ]
    schedule = build_beat_schedule(configs)
    assert set(schedule.keys()) == {"confluence:SPACE_A"}
    entry = schedule["confluence:SPACE_A"]
    assert entry["task"] == CONFLUENCE_SYNC_TASK
    assert entry["schedule"] == 3600.0
    assert entry["kwargs"]["scope_key"] == "SPACE_A"
    assert entry["kwargs"]["project_id"] == str(
        uuid.UUID("00000000-0000-4000-8000-000000000aaa"),
    )


async def test_run_confluence_sync_invokes_connector_sync(monkeypatch):
    """``run_confluence_sync`` builds a connector and calls sync()."""
    from breadmind.kb.connectors import schedule as sched_mod

    built: dict = {}

    class DummyConn:
        def __init__(self, **kw):
            built.update(kw)

        async def sync(self, project_id, scope_key, cursor):
            built["sync_called"] = (project_id, scope_key, cursor)
            from breadmind.kb.connectors.base import SyncResult
            return SyncResult(new_cursor="C", processed=1, errors=0)

        async def load_cursor(self, scope_key):
            return "CURSOR-PRIOR"

    monkeypatch.setattr(sched_mod, "_build_confluence_connector",
                         AsyncMock(return_value=DummyConn()))

    pid = "00000000-0000-4000-8000-000000000aaa"
    result = await run_confluence_sync(
        project_id=pid,
        scope_key="SPACE_A",
        base_url="https://x",
        credentials_ref="confluence:a",
    )
    assert result == {"processed": 1, "errors": 0, "new_cursor": "C"}
