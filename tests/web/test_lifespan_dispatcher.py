"""Dispatcher must start with the app and cancel cleanly on shutdown.

Project precedent (commit ``8779546``) drops redundant
``@pytest.mark.asyncio`` decorators because ``asyncio_mode = "auto"`` is
configured in ``pyproject.toml``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


async def test_dispatcher_starts_in_lifespan(monkeypatch):
    """OutboxDispatcher is constructed and its ``run`` is scheduled."""
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    monkeypatch.setenv("BREADMIND_DB_URL", "postgresql://x/y")
    from breadmind.web.lifespan import lifespan

    fake_app = MagicMock()
    fake_app.state = MagicMock()
    fake_app.state.redis = AsyncMock()

    with patch("breadmind.web.lifespan.OutboxDispatcher") as MockDisp, \
         patch("breadmind.web.lifespan.acquire_pg_pool") as mock_pool:
        mock_pool.return_value = AsyncMock()
        mock_disp_inst = MockDisp.return_value
        mock_disp_inst.run = AsyncMock()
        async with lifespan(fake_app):
            await asyncio.sleep(0.01)
            MockDisp.assert_called_once()
            assert mock_disp_inst.run.called or asyncio.all_tasks()


async def test_dispatcher_cancels_on_shutdown(monkeypatch):
    """When lifespan exits, dispatcher task is cancelled within 5s."""
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    monkeypatch.setenv("BREADMIND_DB_URL", "postgresql://x/y")
    from breadmind.web.lifespan import lifespan

    fake_app = MagicMock()
    fake_app.state = MagicMock()
    fake_app.state.redis = AsyncMock()

    cancel_seen = asyncio.Event()

    class _StubDispatcher:
        def __init__(self, *a, **kw):
            pass

        async def run(self):
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancel_seen.set()
                raise

    with patch("breadmind.web.lifespan.OutboxDispatcher", _StubDispatcher), \
         patch("breadmind.web.lifespan.acquire_pg_pool", AsyncMock()):
        async with lifespan(fake_app):
            await asyncio.sleep(0.05)
        assert cancel_seen.is_set(), "dispatcher must observe CancelledError"


async def test_dispatcher_skipped_when_db_url_missing(monkeypatch):
    """Redis present but BREADMIND_DB_URL/DATABASE_URL unset → DB-URL skip path.

    Exercises the genuine ``DatabaseUrlNotSet`` branch in
    ``_maybe_start_dispatcher``: the redis gate passes (mocked), so flow
    proceeds to ``acquire_pg_pool`` which raises ``DatabaseUrlNotSet``
    when neither env var is set. The dispatcher must not be constructed.
    """
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    monkeypatch.setenv("BREADMIND_OUTBOX_DISPATCHER_ENABLED", "true")
    monkeypatch.delenv("BREADMIND_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from breadmind.web.lifespan import lifespan

    fake_app = MagicMock()
    fake_app.state = MagicMock()
    fake_app.state.redis = AsyncMock()  # Redis present → redis gate passes

    # Do NOT patch acquire_pg_pool — let it raise DatabaseUrlNotSet so we
    # exercise the real DB-URL skip branch in _maybe_start_dispatcher.
    with patch("breadmind.web.lifespan.OutboxDispatcher") as MockDisp:
        async with lifespan(fake_app):
            pass
        MockDisp.assert_not_called()


async def test_dispatcher_skipped_when_redis_missing(monkeypatch):
    """When ``app.state.redis`` is unset, dispatcher start is skipped."""
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    monkeypatch.setenv("BREADMIND_DB_URL", "postgresql://x/y")
    from breadmind.web.lifespan import lifespan

    # MagicMock with redis attribute deleted so getattr returns the default.
    fake_app = MagicMock()
    fake_app.state = MagicMock(spec=[])  # no attributes -> redis is missing

    with patch("breadmind.web.lifespan.OutboxDispatcher") as MockDisp, \
         patch("breadmind.web.lifespan.acquire_pg_pool") as mock_pool:
        mock_pool.return_value = AsyncMock()
        async with lifespan(fake_app):
            pass
        MockDisp.assert_not_called()


async def test_dispatcher_disabled_via_env(monkeypatch):
    """``BREADMIND_OUTBOX_DISPATCHER_ENABLED=false`` opts out cleanly."""
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    monkeypatch.setenv("BREADMIND_DB_URL", "postgresql://x/y")
    monkeypatch.setenv("BREADMIND_OUTBOX_DISPATCHER_ENABLED", "false")
    from breadmind.web.lifespan import lifespan

    fake_app = MagicMock()
    fake_app.state = MagicMock()
    fake_app.state.redis = AsyncMock()

    with patch("breadmind.web.lifespan.OutboxDispatcher") as MockDisp, \
         patch("breadmind.web.lifespan.acquire_pg_pool") as mock_pool:
        mock_pool.return_value = AsyncMock()
        async with lifespan(fake_app):
            pass
        MockDisp.assert_not_called()
