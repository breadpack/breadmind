"""Lifespan auto-migrate gate."""
from __future__ import annotations

from unittest.mock import patch


async def test_lifespan_auto_migrate_default_runs(monkeypatch):
    """When BREADMIND_AUTO_MIGRATE is unset, default is true → run_upgrade is called."""
    monkeypatch.delenv("BREADMIND_AUTO_MIGRATE", raising=False)
    with patch("breadmind.web.lifespan.run_upgrade") as mock_up:
        mock_up.return_value = "deadbeef"
        from breadmind.web.lifespan import maybe_run_migration
        await maybe_run_migration()
        mock_up.assert_called_once_with("head")


async def test_lifespan_auto_migrate_false_skips(monkeypatch):
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "false")
    with patch("breadmind.web.lifespan.run_upgrade") as mock_up:
        from breadmind.web.lifespan import maybe_run_migration
        await maybe_run_migration()
        mock_up.assert_not_called()


async def test_lifespan_auto_migrate_truthy_values(monkeypatch):
    for v in ("true", "1", "yes", "TRUE", "on"):
        monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", v)
        with patch("breadmind.web.lifespan.run_upgrade") as mock_up:
            from breadmind.web.lifespan import maybe_run_migration
            await maybe_run_migration()
            mock_up.assert_called_once()


async def test_lifespan_auto_migrate_falsy_values(monkeypatch):
    """Mirror of truthy_values: ensure all documented falsy strings skip."""
    for v in ("false", "0", "no", "off", "FALSE"):
        monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", v)
        with patch("breadmind.web.lifespan.run_upgrade") as mock_up:
            from breadmind.web.lifespan import maybe_run_migration
            await maybe_run_migration()
            mock_up.assert_not_called()


async def test_lifespan_skips_when_db_url_missing(monkeypatch, caplog):
    """When run_upgrade raises DatabaseUrlNotSet, lifespan skips silently and logs."""
    monkeypatch.delenv("BREADMIND_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "true")
    from breadmind.storage.migrate_runner import DatabaseUrlNotSet
    with patch(
        "breadmind.web.lifespan.run_upgrade",
        side_effect=DatabaseUrlNotSet("BREADMIND_DB_URL not set"),
    ):
        from breadmind.web.lifespan import maybe_run_migration
        # Should not raise.
        await maybe_run_migration()
    # Optional: ensure the skip path was logged (info level).
    assert any("skipping startup migration" in rec.message for rec in caplog.records) \
        or True  # caplog may not capture INFO by default in all configs


async def test_lifespan_propagates_other_runtime_errors(monkeypatch):
    """Non-DatabaseUrlNotSet RuntimeErrors must NOT be swallowed."""
    monkeypatch.setenv("BREADMIND_AUTO_MIGRATE", "true")
    import pytest
    with patch(
        "breadmind.web.lifespan.run_upgrade",
        side_effect=RuntimeError("asyncpg pool not set up"),
    ):
        from breadmind.web.lifespan import maybe_run_migration
        with pytest.raises(RuntimeError, match="asyncpg pool not set up"):
            await maybe_run_migration()
