"""SyncEngine conflict resolution tests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest


@pytest.mark.asyncio
async def test_local_wins_when_newer():
    from breadmind.personal.sync import SyncEngine
    engine = SyncEngine()
    now = datetime.now(timezone.utc)
    result = await engine.resolve_conflict(
        "tasks", "t1",
        {"title": "Local", "updated_at": now},
        {"title": "Remote", "updated_at": now - timedelta(hours=1)},
    )
    assert result == "local_wins"


@pytest.mark.asyncio
async def test_remote_wins_when_newer():
    from breadmind.personal.sync import SyncEngine
    engine = SyncEngine()
    now = datetime.now(timezone.utc)
    result = await engine.resolve_conflict(
        "tasks", "t1",
        {"title": "Local", "updated_at": now - timedelta(hours=1)},
        {"title": "Remote", "updated_at": now},
    )
    assert result == "remote_wins"


@pytest.mark.asyncio
async def test_local_wins_on_tie():
    from breadmind.personal.sync import SyncEngine
    engine = SyncEngine()
    now = datetime.now(timezone.utc)
    result = await engine.resolve_conflict(
        "tasks", "t1",
        {"title": "Local", "updated_at": now},
        {"title": "Remote", "updated_at": now},
    )
    assert result == "local_wins"


@pytest.mark.asyncio
async def test_fallback_to_created_at():
    from breadmind.personal.sync import SyncEngine
    engine = SyncEngine()
    now = datetime.now(timezone.utc)
    result = await engine.resolve_conflict(
        "events", "e1",
        {"title": "Local", "created_at": now},
        {"title": "Remote", "created_at": now - timedelta(days=1)},
    )
    assert result == "local_wins"


@pytest.mark.asyncio
async def test_sync_adapter_pulls_new_items():
    from breadmind.personal.sync import SyncEngine
    from breadmind.personal.models import Task

    engine = SyncEngine()
    local = AsyncMock()
    remote = AsyncMock()

    remote_task = Task(id="rt1", title="Remote Task", source_id="rt1")
    remote.list_items = AsyncMock(return_value=[remote_task])
    local.get_item = AsyncMock(return_value=None)
    local.create_item = AsyncMock(return_value="new-id")
    local.domain = "task"

    stats = await engine.sync_adapter(local, remote, user_id="alice")
    assert stats["pulled"] == 1
    local.create_item.assert_called_once()


@pytest.mark.asyncio
async def test_sync_adapter_handles_remote_error():
    from breadmind.personal.sync import SyncEngine
    engine = SyncEngine()
    local = AsyncMock()
    remote = AsyncMock()
    remote.list_items = AsyncMock(side_effect=RuntimeError("Network error"))

    stats = await engine.sync_adapter(local, remote, user_id="alice")
    assert len(stats["errors"]) == 1
    assert "Network error" in stats["errors"][0]
