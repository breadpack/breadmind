"""Tests for CLI backup and restore."""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from breadmind.cli.backup_restore import (
    BackupOptions,
    CLIBackupManager,
)


@pytest.fixture
def setup_dirs(tmp_path: Path):
    """Create user_dir and project_dir with sample files."""
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    user_dir.mkdir()
    project_dir.mkdir()

    # Config files
    (user_dir / "config.yaml").write_text("llm: claude")
    (user_dir / "settings.yaml").write_text("theme: dark")

    # Sessions
    sessions = user_dir / "sessions"
    sessions.mkdir()
    (sessions / "sess_001.json").write_text('{"id": 1}')

    # Memory
    memory = user_dir / "memory"
    memory.mkdir()
    (memory / "episodic.json").write_text("[]")

    # Credentials
    (user_dir / "credentials.json").write_text('{"token": "x"}')

    # Plugins
    plugins = user_dir / "plugins"
    plugins.mkdir()
    (plugins / "hello.py").write_text("print('hello')")

    return user_dir, project_dir


def test_create_and_verify(tmp_path: Path, setup_dirs):
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)
    archive = mgr.create(output_dir=tmp_path / "out")

    assert archive.exists()
    assert archive.name.startswith("breadmind_backup_")
    assert archive.name.endswith(".tar.gz")

    valid, manifest, msg = mgr.verify(archive)
    assert valid is True
    assert manifest is not None
    assert "config" in manifest.includes
    assert manifest.file_count > 0
    assert "valid" in msg.lower()


def test_create_only_config(tmp_path: Path, setup_dirs):
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)
    archive = mgr.create(
        output_dir=tmp_path / "out",
        options=BackupOptions(only_config=True),
    )

    valid, manifest, _ = mgr.verify(archive)
    assert valid
    assert manifest is not None
    assert "config" in manifest.includes
    assert "sessions" not in manifest.includes
    assert "credentials" not in manifest.includes


def test_credentials_opt_in(tmp_path: Path, setup_dirs):
    """Credentials are excluded by default and included when opted in."""
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)

    # Default: no credentials
    archive_no = mgr.create(
        output_dir=tmp_path / "no_creds",
        options=BackupOptions(),
    )
    with tarfile.open(str(archive_no), "r:gz") as tar:
        names = tar.getnames()
    assert not any("credentials" in n for n in names)

    # Opt-in
    archive_yes = mgr.create(
        output_dir=tmp_path / "with_creds",
        options=BackupOptions(include_credentials=True),
    )
    with tarfile.open(str(archive_yes), "r:gz") as tar:
        names = tar.getnames()
    assert any("credentials" in n for n in names)


def test_verify_missing_file(tmp_path: Path):
    mgr = CLIBackupManager(user_dir=tmp_path, project_dir=tmp_path)
    valid, manifest, msg = mgr.verify(tmp_path / "nonexistent.tar.gz")
    assert valid is False
    assert manifest is None
    assert "not found" in msg.lower()


def test_verify_corrupt_archive(tmp_path: Path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tar file at all")
    mgr = CLIBackupManager(user_dir=tmp_path, project_dir=tmp_path)
    valid, manifest, msg = mgr.verify(bad)
    assert valid is False
    assert "corrupt" in msg.lower()


def test_restore_dry_run(tmp_path: Path, setup_dirs):
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)
    archive = mgr.create(output_dir=tmp_path / "out")

    # Restore into fresh dirs
    restore_user = tmp_path / "restore_user"
    restore_project = tmp_path / "restore_project"
    mgr2 = CLIBackupManager(user_dir=restore_user, project_dir=restore_project)

    restored = mgr2.restore(archive, dry_run=True)
    assert len(restored) > 0
    # Files should NOT actually exist in dry-run
    for p in restored:
        assert not Path(p).exists()


def test_restore_actual(tmp_path: Path, setup_dirs):
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)
    archive = mgr.create(output_dir=tmp_path / "out")

    restore_user = tmp_path / "restore_user"
    restore_project = tmp_path / "restore_project"
    mgr2 = CLIBackupManager(user_dir=restore_user, project_dir=restore_project)

    restored = mgr2.restore(archive, dry_run=False)
    assert len(restored) > 0
    # At least one file should exist
    existing = [p for p in restored if Path(p).exists()]
    assert len(existing) > 0


def test_restore_invalid_archive(tmp_path: Path):
    mgr = CLIBackupManager(user_dir=tmp_path, project_dir=tmp_path)
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"garbage")
    with pytest.raises(ValueError, match="Cannot restore"):
        mgr.restore(bad)


def test_list_backups(tmp_path: Path, setup_dirs):
    user_dir, project_dir = setup_dirs
    mgr = CLIBackupManager(user_dir=user_dir, project_dir=project_dir)
    out = tmp_path / "backups"
    mgr.create(output_dir=out)
    mgr.create(output_dir=out)

    backups = mgr.list_backups(out)
    assert len(backups) >= 1  # may be 1 if created in same second
    for path, manifest in backups:
        assert path.exists()
        assert manifest.file_count > 0
