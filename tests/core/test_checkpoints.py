"""Tests for the checkpoint system (edit tracking, rewind, fork)."""

from __future__ import annotations

from pathlib import Path

import pytest

from breadmind.core.checkpoints import CheckpointManager


def test_create_checkpoint_without_files(tmp_path: Path):
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="initial")
    assert cp.label == "initial"
    assert cp.id
    assert len(cp.snapshots) == 0


def test_create_checkpoint_with_files(tmp_path: Path):
    f = tmp_path / "code.py"
    f.write_text("print('hello')\n", encoding="utf-8")
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="snap1", files=[str(f)])
    assert len(cp.snapshots) == 1
    assert cp.snapshots[0].content == "print('hello')\n"


def test_snapshot_file_into_existing_checkpoint(tmp_path: Path):
    f = tmp_path / "extra.py"
    f.write_text("x = 1\n", encoding="utf-8")
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="base")
    mgr.snapshot_file(cp.id, str(f))
    assert len(cp.snapshots) == 1
    assert cp.snapshots[0].content == "x = 1\n"


def test_snapshot_file_missing_raises(tmp_path: Path):
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="base")
    with pytest.raises(FileNotFoundError):
        mgr.snapshot_file(cp.id, str(tmp_path / "nonexistent.py"))


def test_rewind_returns_snapshots(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("v1\n", encoding="utf-8")
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp1 = mgr.create(label="v1", files=[str(f)])
    f.write_text("v2\n", encoding="utf-8")
    mgr.create(label="v2", files=[str(f)])

    snapshots = mgr.rewind(cp1.id)
    assert len(snapshots) == 1
    assert snapshots[0].content == "v1\n"


def test_restore_writes_files(tmp_path: Path):
    f = tmp_path / "data.py"
    f.write_text("original\n", encoding="utf-8")
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="save", files=[str(f)])

    # Modify file
    f.write_text("modified\n", encoding="utf-8")
    assert f.read_text(encoding="utf-8") == "modified\n"

    # Restore
    restored = mgr.restore(cp.id)
    assert str(f) in restored
    assert f.read_text(encoding="utf-8") == "original\n"


def test_fork_creates_independent_copy(tmp_path: Path):
    f = tmp_path / "src.py"
    f.write_text("base\n", encoding="utf-8")
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    cp = mgr.create(label="main", files=[str(f)])

    forked = mgr.fork(cp.id, label="experiment")
    assert forked.parent_id == cp.id
    assert forked.id != cp.id
    assert len(forked.snapshots) == 1
    assert forked.snapshots[0].content == "base\n"

    # Modifying fork snapshot doesn't affect original
    forked.snapshots[0].content = "changed\n"
    assert cp.snapshots[0].content == "base\n"


def test_list_checkpoints(tmp_path: Path):
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    mgr.create(label="a")
    mgr.create(label="b")
    mgr.create(label="c")
    cps = mgr.list_checkpoints()
    assert len(cps) == 3
    assert [c.label for c in cps] == ["a", "b", "c"]


def test_get_returns_none_for_unknown(tmp_path: Path):
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    assert mgr.get("nonexistent") is None


def test_save_and_load_round_trip(tmp_path: Path):
    f = tmp_path / "file.py"
    f.write_text("content\n", encoding="utf-8")
    storage = tmp_path / "cp"

    mgr1 = CheckpointManager(storage_dir=storage)
    cp = mgr1.create(label="saved", files=[str(f)], message_index=5)
    mgr1.save_to_disk()

    mgr2 = CheckpointManager(storage_dir=storage)
    mgr2.load_from_disk()
    loaded = mgr2.list_checkpoints()
    assert len(loaded) == 1
    assert loaded[0].id == cp.id
    assert loaded[0].label == "saved"
    assert loaded[0].message_index == 5
    assert loaded[0].snapshots[0].content == "content\n"


def test_fork_unknown_checkpoint_raises(tmp_path: Path):
    mgr = CheckpointManager(storage_dir=tmp_path / "cp")
    with pytest.raises(ValueError, match="not found"):
        mgr.fork("nonexistent")
