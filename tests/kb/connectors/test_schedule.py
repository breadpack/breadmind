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


async def test_reload_beat_schedule_from_db_installs_schedule(monkeypatch):
    """``reload_beat_schedule_from_db`` reads configs and installs on celery."""
    from breadmind.kb.connectors import schedule as sched_mod
    from breadmind.tasks.celery_app import celery_app

    cfg = MagicMock(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        connector="confluence",
        scope_key="SPACE_A",
        project_id=uuid.UUID("00000000-0000-4000-8000-000000000aaa"),
        settings={"base_url": "https://x", "credentials_ref": "confluence:a"},
        enabled=True,
    )

    class StubStore:
        def __init__(self, db):
            self._db = db

        async def list(self, *, connector, enabled_only):
            assert connector == "confluence"
            assert enabled_only is True
            return [cfg]

    import breadmind.kb.connectors.configs_store as cs_mod
    monkeypatch.setattr(cs_mod, "ConnectorConfigsStore", StubStore)

    original_schedule = celery_app.conf.beat_schedule
    try:
        await sched_mod.reload_beat_schedule_from_db(db=MagicMock())
        assert "confluence:SPACE_A" in celery_app.conf.beat_schedule
    finally:
        celery_app.conf.beat_schedule = original_schedule


def test_beat_init_reload_handler_is_wired():
    """The connector-schedule reload handler is registered on ``beat_init``.

    Re-importing the celery_app module on every Beat start would be the
    only guarantee Beat has a fresh schedule at boot; without a signal
    handler, the schedule stays empty until the next ``/api/connectors``
    write. The handler itself is best-effort (catches all exceptions and
    logs), so the only contract we can lock in a unit test is that it is
    actually attached to the ``beat_init`` signal.
    """
    from celery.signals import beat_init
    # ``beat_init.receivers`` is a list of ``(lookup_key, ref)`` tuples.
    import breadmind.tasks.celery_app  # noqa: F401 - ensure handler registered
    assert beat_init.receivers, "beat_init has no receivers registered"
    names = []
    for _key, ref in beat_init.receivers:
        target = ref() if callable(ref) else ref
        if target is None:
            continue
        names.append(getattr(target, "__name__", repr(target)))
    assert any("reload_connector_schedule" in n for n in names), (
        f"no connector-schedule reload handler on beat_init; found {names}"
    )


def test_beat_init_handler_invokes_reload_and_skips_without_dsn(monkeypatch):
    """The handler delegates to ``reload_beat_schedule_from_db`` when DSN is set,
    and no-ops (without raising) when no DSN is configured."""
    import breadmind.tasks.celery_app as celery_mod

    # ── Path 1: no DSN → log + return, no reload. ───────────────────
    monkeypatch.delenv("BREADMIND_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    called = {"n": 0}

    def _boom(*a, **kw):  # pragma: no cover - must not be called
        called["n"] += 1

    # Patch the lazy imports so a stray call would blow up loudly.
    import breadmind.kb.connectors.schedule as sched_mod
    monkeypatch.setattr(sched_mod, "reload_beat_schedule_from_db", _boom)
    celery_mod._reload_connector_schedule_on_beat_init(sender=None)
    assert called["n"] == 0

    # ── Path 2: DSN set → reload invoked exactly once. ──────────────
    monkeypatch.setenv("BREADMIND_DSN", "postgresql://stub")

    async def _fake_reload(db):
        called["n"] += 1

    class _FakeDB:
        def __init__(self, dsn):
            pass

        async def connect(self):
            return None

        async def disconnect(self):
            return None

    monkeypatch.setattr(sched_mod, "reload_beat_schedule_from_db", _fake_reload)
    import breadmind.storage.database as db_mod
    monkeypatch.setattr(db_mod, "Database", _FakeDB)
    celery_mod._reload_connector_schedule_on_beat_init(sender=None)
    assert called["n"] == 1


def test_confluence_sync_task_runs_async_body(monkeypatch):
    """The Celery task entrypoint dispatches to ``run_confluence_sync``."""
    from breadmind.kb.connectors import schedule as sched_mod

    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return {"processed": 2, "errors": 0, "new_cursor": "X"}

    monkeypatch.setattr(sched_mod, "run_confluence_sync", fake_run)

    # Invoke via the undecorated callable the task wraps.
    task = sched_mod.confluence_sync_task
    result = task.run(
        project_id="00000000-0000-4000-8000-000000000aaa",
        scope_key="SPACE_A",
        base_url="https://x",
        credentials_ref="confluence:a",
    )
    assert result == {"processed": 2, "errors": 0, "new_cursor": "X"}
    assert captured["scope_key"] == "SPACE_A"
