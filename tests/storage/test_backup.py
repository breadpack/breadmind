"""Tests for breadmind.storage.backup module."""
from __future__ import annotations

import gzip
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from breadmind.storage.backup import (
    BackupConfig,
    BackupError,
    BackupInfo,
    BackupManager,
)


# ── Dataclass tests ──────────────────────────────────────────────


def test_backup_config_defaults():
    cfg = BackupConfig()
    assert cfg.backup_dir == "backups"
    assert cfg.max_backups == 10
    assert cfg.compress is True


def test_backup_info_creation():
    now = datetime.now(timezone.utc)
    info = BackupInfo(
        filename="breadmind_testdb_20260405_120000.sql.gz",
        path="/backups/breadmind_testdb_20260405_120000.sql.gz",
        size_bytes=1024,
        created_at=now,
        database="testdb",
        compressed=True,
    )
    assert info.filename == "breadmind_testdb_20260405_120000.sql.gz"
    assert info.size_bytes == 1024
    assert info.database == "testdb"
    assert info.compressed is True

    d = info.to_dict()
    assert d["filename"] == info.filename
    assert d["size_bytes"] == 1024
    assert d["compressed"] is True


# ── List / cleanup / delete tests ────────────────────────────────


def test_list_backups_empty(tmp_path):
    cfg = BackupConfig(backup_dir=str(tmp_path / "empty_backups"))
    mgr = BackupManager({"name": "testdb"}, cfg)
    assert mgr.list_backups() == []


def test_list_backups_with_files(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Create some fake backup files
    (backup_dir / "breadmind_testdb_20260401_100000.sql.gz").write_bytes(b"fake1")
    (backup_dir / "breadmind_testdb_20260402_100000.sql").write_bytes(b"fake2")
    (backup_dir / "unrelated.txt").write_bytes(b"ignore")

    cfg = BackupConfig(backup_dir=str(backup_dir))
    mgr = BackupManager({"name": "testdb"}, cfg)
    backups = mgr.list_backups()

    assert len(backups) == 2
    filenames = {b.filename for b in backups}
    assert "breadmind_testdb_20260401_100000.sql.gz" in filenames
    assert "breadmind_testdb_20260402_100000.sql" in filenames
    # Newest first
    assert backups[0].created_at >= backups[1].created_at


def test_cleanup_old(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Create 5 backups, max is 3
    for i in range(5):
        (backup_dir / f"breadmind_testdb_2026040{i}_100000.sql.gz").write_bytes(
            b"x" * (i + 1)
        )

    cfg = BackupConfig(backup_dir=str(backup_dir), max_backups=3)
    mgr = BackupManager({"name": "testdb"}, cfg)
    deleted = mgr.cleanup_old()

    assert deleted == 2
    remaining = mgr.list_backups()
    assert len(remaining) == 3


def test_delete_backup(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "test_backup.sql.gz").write_bytes(b"data")

    cfg = BackupConfig(backup_dir=str(backup_dir))
    mgr = BackupManager({"name": "testdb"}, cfg)

    assert mgr.delete_backup("test_backup.sql.gz") is True
    assert not (backup_dir / "test_backup.sql.gz").exists()
    assert mgr.delete_backup("nonexistent.sql.gz") is False


# ── create_backup tests (with mocked subprocess) ─────────────────


@pytest.fixture
def db_config():
    return {
        "host": "localhost",
        "port": 5432,
        "name": "breadmind",
        "user": "breadmind",
        "password": "secret",
    }


def _make_mock_process(returncode=0, stdout=b"-- SQL dump", stderr=b""):
    """Create a mock async subprocess."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


async def test_create_backup_success(tmp_path, db_config):
    cfg = BackupConfig(backup_dir=str(tmp_path / "backups"), compress=True)
    mgr = BackupManager(db_config, cfg)

    mock_proc = _make_mock_process(stdout=b"-- PostgreSQL dump\nCREATE TABLE test;")

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        info = await mgr.create_backup(label="test")

    assert info.filename.startswith("breadmind_breadmind_")
    assert info.filename.endswith("_test.sql.gz")
    assert info.size_bytes > 0
    assert info.compressed is True
    assert info.database == "breadmind"
    assert Path(info.path).exists()


async def test_create_backup_failure(tmp_path, db_config):
    cfg = BackupConfig(backup_dir=str(tmp_path / "backups"), compress=True)
    mgr = BackupManager(db_config, cfg)

    mock_proc = _make_mock_process(returncode=1, stdout=b"", stderr=b"connection refused")

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(BackupError, match="pg_dump failed"):
            await mgr.create_backup()


async def test_create_backup_tool_missing(tmp_path, db_config):
    cfg = BackupConfig(backup_dir=str(tmp_path / "backups"))
    mgr = BackupManager(db_config, cfg)

    with patch("shutil.which", return_value=None):
        with pytest.raises(BackupError, match="not installed"):
            await mgr.create_backup()


# ── restore_backup tests ─────────────────────────────────────────


async def test_restore_backup(tmp_path, db_config):
    # Create a fake compressed backup
    backup_file = tmp_path / "test_restore.sql.gz"
    with gzip.open(backup_file, "wb") as f:
        f.write(b"-- PostgreSQL dump\nCREATE TABLE test;")

    cfg = BackupConfig(backup_dir=str(tmp_path))
    mgr = BackupManager(db_config, cfg)

    mock_proc = _make_mock_process()

    with patch("shutil.which", return_value="/usr/bin/psql"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.restore_backup(str(backup_file))

    assert result is True
    # Verify psql was called with stdin data
    mock_proc.communicate.assert_called_once()


async def test_restore_backup_file_not_found(tmp_path, db_config):
    cfg = BackupConfig(backup_dir=str(tmp_path))
    mgr = BackupManager(db_config, cfg)

    with pytest.raises(BackupError, match="not found"):
        await mgr.restore_backup("/nonexistent/file.sql.gz")


async def test_restore_backup_plain_sql(tmp_path, db_config):
    backup_file = tmp_path / "test_restore.sql"
    backup_file.write_text("-- PostgreSQL dump\nCREATE TABLE test;")

    cfg = BackupConfig(backup_dir=str(tmp_path))
    mgr = BackupManager(db_config, cfg)

    mock_proc = _make_mock_process()

    with patch("shutil.which", return_value="/usr/bin/psql"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.restore_backup(str(backup_file))

    assert result is True


# ── verify_backup tests ──────────────────────────────────────────


async def test_verify_backup(tmp_path):
    # Valid gzip backup with SQL content
    backup_file = tmp_path / "valid.sql.gz"
    with gzip.open(backup_file, "wb") as f:
        f.write(b"-- PostgreSQL database dump\nCREATE TABLE test;")

    mgr = BackupManager({"name": "testdb"}, BackupConfig(backup_dir=str(tmp_path)))
    assert await mgr.verify_backup(str(backup_file)) is True


async def test_verify_backup_invalid_gzip(tmp_path):
    backup_file = tmp_path / "corrupt.sql.gz"
    backup_file.write_bytes(b"this is not gzip data")

    mgr = BackupManager({"name": "testdb"}, BackupConfig(backup_dir=str(tmp_path)))
    assert await mgr.verify_backup(str(backup_file)) is False


async def test_verify_backup_nonexistent(tmp_path):
    mgr = BackupManager({"name": "testdb"}, BackupConfig(backup_dir=str(tmp_path)))
    assert await mgr.verify_backup("/no/such/file.sql.gz") is False


async def test_verify_backup_plain_sql(tmp_path):
    backup_file = tmp_path / "valid.sql"
    backup_file.write_text("-- PostgreSQL dump\nSET statement_timeout = 0;")

    mgr = BackupManager({"name": "testdb"}, BackupConfig(backup_dir=str(tmp_path)))
    assert await mgr.verify_backup(str(backup_file)) is True


async def test_verify_backup_invalid_content(tmp_path):
    backup_file = tmp_path / "bad_content.sql"
    backup_file.write_text("This is not SQL at all, just random text.")

    mgr = BackupManager({"name": "testdb"}, BackupConfig(backup_dir=str(tmp_path)))
    assert await mgr.verify_backup(str(backup_file)) is False
