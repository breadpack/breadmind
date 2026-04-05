"""Tests for VCS abstraction layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from breadmind.core.vcs import (
    GitBackend,
    JujutsuBackend,
    SaplingBackend,
    VCSManager,
    VCSStatus,
    VCSType,
)


def test_detect_git(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.detect() == VCSType.GIT


def test_detect_jujutsu(tmp_path: Path):
    (tmp_path / ".jj").mkdir()
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.detect() == VCSType.JUJUTSU


def test_detect_sapling(tmp_path: Path):
    (tmp_path / ".sl").mkdir()
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.detect() == VCSType.SAPLING


def test_detect_none(tmp_path: Path):
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.detect() is None


def test_backend_raises_when_none(tmp_path: Path):
    mgr = VCSManager(project_root=tmp_path)
    with pytest.raises(RuntimeError, match="No VCS detected"):
        _ = mgr.backend


def test_detect_priority_git_first(tmp_path: Path):
    """Git is checked first when multiple VCS dirs exist."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".jj").mkdir()
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.detect() == VCSType.GIT


def test_vcs_type_property(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    mgr = VCSManager(project_root=tmp_path)
    assert mgr.vcs_type == VCSType.GIT


async def test_git_status_parse():
    backend = GitBackend()
    porcelain = " M src/main.py\n?? newfile.txt\nA  added.py\n D deleted.py\n"
    with patch.object(backend, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            porcelain,  # status
            "main",  # current_branch
        ]
        status = await backend.status(Path("/fake"))
    assert "src/main.py" in status.modified
    assert "newfile.txt" in status.untracked
    assert "added.py" in status.added
    assert "deleted.py" in status.deleted


async def test_git_diff():
    backend = GitBackend()
    with patch.object(backend, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "diff --git a/f.py b/f.py\n+new line\n"
        result = await backend.diff(Path("/fake"), staged=True)
    assert "+new line" in result
    mock_run.assert_called_once_with(["git", "diff", "--cached"], Path("/fake"))


async def test_git_log_parse():
    backend = GitBackend()
    log_output = (
        "abc123\nFix bug\nAlice\n2025-01-01 12:00:00\n---\n"
        "def456\nAdd feature\nBob\n2025-01-02 12:00:00\n---\n"
    )
    with patch.object(backend, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = log_output
        commits = await backend.log(Path("/fake"), limit=2)
    assert len(commits) == 2
    assert commits[0].hash == "abc123"
    assert commits[0].message == "Fix bug"
    assert commits[1].author == "Bob"


async def test_git_current_branch():
    backend = GitBackend()
    with patch.object(backend, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "feature/test\n"
        branch = await backend.current_branch(Path("/fake"))
    assert branch == "feature/test"
