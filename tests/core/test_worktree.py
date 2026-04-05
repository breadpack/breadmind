"""Tests for git worktree manager."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.core.worktree import WorktreeManager


def _mock_process(returncode: int = 0, stdout: bytes = b"",
                  stderr: bytes = b"") -> AsyncMock:
    """Create a mock subprocess."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@patch("asyncio.create_subprocess_exec")
async def test_create_worktree(mock_exec: AsyncMock) -> None:
    mock_exec.return_value = _mock_process(returncode=0)

    mgr = WorktreeManager(repo_path="/fake/repo")
    info = await mgr.create("agent_1", base_branch="main")

    assert info.agent_id == "agent_1"
    assert info.base_branch == "main"
    assert info.id.startswith("wt_")
    assert "agent_1" in info.branch
    assert info.path.endswith(info.id)
    mock_exec.assert_called_once()


@patch("asyncio.create_subprocess_exec")
async def test_remove_worktree_no_changes(mock_exec: AsyncMock) -> None:
    # First call: create worktree
    # Second call: git status --porcelain (no changes)
    # Third call: git worktree remove
    # Fourth call: git branch -D
    mock_exec.side_effect = [
        _mock_process(returncode=0),  # create
        _mock_process(returncode=0, stdout=b""),  # status --porcelain
        _mock_process(returncode=0),  # worktree remove
        _mock_process(returncode=0),  # branch -D
    ]

    mgr = WorktreeManager(repo_path="/fake/repo")
    info = await mgr.create("agent_1")
    removed = await mgr.remove(info.id, force=False)

    assert removed is True
    assert mgr.get_worktree(info.id) is None


@patch("asyncio.create_subprocess_exec")
async def test_remove_worktree_with_changes_not_forced(mock_exec: AsyncMock) -> None:
    mock_exec.side_effect = [
        _mock_process(returncode=0),  # create
        _mock_process(returncode=0, stdout=b"M file.py\n"),  # status (has changes)
    ]

    mgr = WorktreeManager(repo_path="/fake/repo")
    info = await mgr.create("agent_1")
    removed = await mgr.remove(info.id, force=False)

    assert removed is False
    # Worktree should still exist
    assert mgr.get_worktree(info.id) is not None
    assert mgr.get_worktree(info.id).has_changes is True


@patch("asyncio.create_subprocess_exec")
async def test_cleanup_all(mock_exec: AsyncMock) -> None:
    # Create two worktrees, then cleanup both
    mock_exec.side_effect = [
        _mock_process(returncode=0),  # create wt1
        _mock_process(returncode=0),  # create wt2
        _mock_process(returncode=0, stdout=b""),  # status wt1
        _mock_process(returncode=0),  # remove wt1
        _mock_process(returncode=0),  # branch -D wt1
        _mock_process(returncode=0, stdout=b""),  # status wt2
        _mock_process(returncode=0),  # remove wt2
        _mock_process(returncode=0),  # branch -D wt2
    ]

    mgr = WorktreeManager(repo_path="/fake/repo")
    await mgr.create("agent_1")
    await mgr.create("agent_2")

    removed = await mgr.cleanup_all()
    assert removed == 2
    assert len(mgr.list_worktrees()) == 0


async def test_get_agent_worktree() -> None:
    mgr = WorktreeManager(repo_path="/fake/repo")
    # Manually inject a worktree info
    from breadmind.core.worktree import WorktreeInfo
    info = WorktreeInfo(
        id="wt_test", path="/fake/path", branch="breadmind/a1/wt_test",
        base_branch="main", agent_id="a1",
    )
    mgr._worktrees["wt_test"] = info

    result = mgr.get_agent_worktree("a1")
    assert result is not None
    assert result.id == "wt_test"

    result2 = mgr.get_agent_worktree("nonexistent")
    assert result2 is None


async def test_list_worktrees() -> None:
    mgr = WorktreeManager(repo_path="/fake/repo")
    from breadmind.core.worktree import WorktreeInfo
    mgr._worktrees["wt_1"] = WorktreeInfo(
        id="wt_1", path="/p1", branch="b1", base_branch="main", agent_id="a1",
    )
    mgr._worktrees["wt_2"] = WorktreeInfo(
        id="wt_2", path="/p2", branch="b2", base_branch="main", agent_id="a2",
    )

    wts = mgr.list_worktrees()
    assert len(wts) == 2


@patch("asyncio.create_subprocess_exec")
async def test_check_changes(mock_exec: AsyncMock) -> None:
    mock_exec.return_value = _mock_process(returncode=0, stdout=b"M something.py\n")

    mgr = WorktreeManager(repo_path="/fake/repo")
    has_changes = await mgr._check_changes("/some/path")
    assert has_changes is True

    mock_exec.return_value = _mock_process(returncode=0, stdout=b"")
    has_changes = await mgr._check_changes("/some/path")
    assert has_changes is False


@patch("os.makedirs")
@patch("asyncio.create_subprocess_exec")
async def test_create_makes_directory(mock_exec: AsyncMock, mock_makedirs: MagicMock) -> None:
    mock_exec.return_value = _mock_process(returncode=0)

    mgr = WorktreeManager(repo_path="/fake/repo", worktree_dir="/fake/worktrees")
    await mgr.create("agent_1")

    mock_makedirs.assert_called_once_with("/fake/worktrees", exist_ok=True)
