"""Tests for the Migrator class and MigrationConfig."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from breadmind.storage.migrator import (
    MigrationConfig,
    Migrator,
    _asyncpg_to_sqlalchemy,
    _MIGRATIONS_DIR,
    run_migration_command,
)


class TestMigrationConfig:
    """MigrationConfig dataclass tests."""

    def test_defaults(self) -> None:
        config = MigrationConfig()
        assert config.migrations_dir == str(_MIGRATIONS_DIR)

    def test_custom_database_url(self) -> None:
        config = MigrationConfig(database_url="postgresql://localhost/test")
        assert config.database_url == "postgresql://localhost/test"

    def test_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://env-host/db")
        config = MigrationConfig()
        assert config.database_url == "postgresql://env-host/db"

    def test_custom_migrations_dir(self, tmp_path: Path) -> None:
        config = MigrationConfig(migrations_dir=str(tmp_path))
        assert config.migrations_dir == str(tmp_path)


class TestAsyncpgToSqlalchemy:
    """URL conversion helper tests."""

    def test_postgresql_plain(self) -> None:
        assert _asyncpg_to_sqlalchemy("postgresql://host/db") == \
            "postgresql+psycopg2://host/db"

    def test_postgres_shorthand(self) -> None:
        assert _asyncpg_to_sqlalchemy("postgres://host/db") == \
            "postgresql+psycopg2://host/db"

    def test_postgresql_asyncpg_driver(self) -> None:
        assert _asyncpg_to_sqlalchemy("postgresql+asyncpg://host/db") == \
            "postgresql+psycopg2://host/db"

    def test_already_psycopg2(self) -> None:
        url = "postgresql+psycopg2://host/db"
        assert _asyncpg_to_sqlalchemy(url) == url

    def test_unknown_scheme(self) -> None:
        url = "sqlite:///test.db"
        assert _asyncpg_to_sqlalchemy(url) == url


class TestMigratorInit:
    """Migrator initialization and configuration tests."""

    def test_init_default_config(self) -> None:
        migrator = Migrator()
        assert migrator._config.migrations_dir == str(_MIGRATIONS_DIR)

    def test_init_custom_config(self) -> None:
        config = MigrationConfig(
            database_url="postgresql://localhost/test",
            migrations_dir=str(_MIGRATIONS_DIR),
        )
        migrator = Migrator(config=config)
        assert migrator._config.database_url == "postgresql://localhost/test"

    def test_migrations_dir_property(self) -> None:
        migrator = Migrator()
        assert migrator.migrations_dir == str(_MIGRATIONS_DIR)

    def test_alembic_config_has_script_location(self) -> None:
        migrator = Migrator()
        assert migrator._alembic_cfg.get_main_option("script_location") == \
            str(_MIGRATIONS_DIR)

    def test_alembic_config_has_sqlalchemy_url(self) -> None:
        config = MigrationConfig(database_url="postgresql://host/db")
        migrator = Migrator(config=config)
        url = migrator._alembic_cfg.get_main_option("sqlalchemy.url")
        assert url == "postgresql+psycopg2://host/db"


class TestMigratorHistory:
    """Migrator.history() tests (no DB required)."""

    def test_history_returns_list(self) -> None:
        migrator = Migrator()
        entries = migrator.history()
        assert isinstance(entries, list)

    def test_history_not_empty(self) -> None:
        """At least the baseline migration should exist."""
        migrator = Migrator()
        entries = migrator.history()
        assert len(entries) >= 1

    def test_baseline_in_history(self) -> None:
        migrator = Migrator()
        entries = migrator.history()
        revisions = [e["revision"] for e in entries]
        assert "001_baseline" in revisions

    def test_history_entry_structure(self) -> None:
        migrator = Migrator()
        entries = migrator.history()
        entry = entries[0]
        assert "revision" in entry
        assert "down_revision" in entry
        assert "description" in entry
        assert "path" in entry


class TestBaselineMigrationExists:
    """Verify the baseline migration file is present and well-formed."""

    def test_baseline_file_exists(self) -> None:
        baseline = _MIGRATIONS_DIR / "versions" / "001_baseline.py"
        assert baseline.exists(), f"Baseline migration not found at {baseline}"

    def test_baseline_has_upgrade_and_downgrade(self) -> None:
        import importlib
        m = importlib.import_module(
            "breadmind.storage.migrations.versions.001_baseline",
        )
        assert hasattr(m, "upgrade")
        assert hasattr(m, "downgrade")
        assert callable(m.upgrade)
        assert callable(m.downgrade)

    def test_baseline_revision_id(self) -> None:
        import importlib
        m = importlib.import_module(
            "breadmind.storage.migrations.versions.001_baseline",
        )
        assert m.revision == "001_baseline"
        assert m.down_revision is None


class TestCheckMethod:
    """Migrator.check() tests (mocked DB)."""

    def test_check_returns_true_when_at_head(self) -> None:
        migrator = Migrator(MigrationConfig(database_url="postgresql://localhost/test"))
        head = migrator.script_directory.get_current_head()
        with patch.object(migrator, "current_revision", return_value=head):
            assert migrator.check() is True

    def test_check_returns_false_when_behind(self) -> None:
        migrator = Migrator(MigrationConfig(database_url="postgresql://localhost/test"))
        with patch.object(migrator, "current_revision", return_value=None):
            assert migrator.check() is False


class TestRunMigrationCommand:
    """run_migration_command() CLI entry point tests."""

    def test_unknown_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(MigrationConfig, "__post_init__"):
            config = MigrationConfig.__new__(MigrationConfig)
            config.database_url = "postgresql://localhost/test"
            config.migrations_dir = str(_MIGRATIONS_DIR)
            with patch("breadmind.storage.migrator.Migrator") as MockMigrator:
                instance = MagicMock()
                instance._config = config
                MockMigrator.return_value = instance
                run_migration_command("nonexistent")
                captured = capsys.readouterr()
                assert "Unknown migration command" in captured.out

    def test_downgrade_requires_revision(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(MigrationConfig, "__post_init__"):
            config = MigrationConfig.__new__(MigrationConfig)
            config.database_url = "postgresql://localhost/test"
            config.migrations_dir = str(_MIGRATIONS_DIR)
            with patch("breadmind.storage.migrator.Migrator") as MockMigrator:
                instance = MagicMock()
                instance._config = config
                MockMigrator.return_value = instance
                run_migration_command("downgrade")
                captured = capsys.readouterr()
                assert "requires a target revision" in captured.out

    def test_no_database_url(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        run_migration_command("check")
        captured = capsys.readouterr()
        assert "DATABASE_URL" in captured.out
