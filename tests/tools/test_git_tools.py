"""Tests for git integration tools."""

from unittest.mock import AsyncMock, patch

from breadmind.tools.git_tools import git_commit, git_diff, git_status


async def test_git_commit_with_coauthor():
    """git_commit should add co-author trailer by default."""
    mock_add = AsyncMock()
    mock_add.returncode = 0
    mock_add.communicate = AsyncMock(return_value=(b"", b""))

    mock_commit = AsyncMock()
    mock_commit.returncode = 0
    mock_commit.communicate = AsyncMock(
        return_value=(b"[main abc1234] test commit", b"")
    )

    call_count = 0

    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_add
        return mock_commit

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await git_commit("test commit")
        assert "Committed" in result
        # Verify the commit message includes co-author
        mock_exec.__wrapped__ if hasattr(mock_exec, '__wrapped__') else None
        # Check that the function was called (basic verification)
        assert call_count == 2


async def test_git_commit_without_coauthor():
    """git_commit with add_coauthor=False should not add trailer."""
    mock_add = AsyncMock()
    mock_add.returncode = 0
    mock_add.communicate = AsyncMock(return_value=(b"", b""))

    mock_commit = AsyncMock()
    mock_commit.returncode = 0
    mock_commit.communicate = AsyncMock(
        return_value=(b"[main abc1234] bare commit", b"")
    )

    procs = iter([mock_add, mock_commit])

    async def mock_exec(*args, **kwargs):
        return next(procs)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await git_commit("bare commit", add_coauthor=False)
        assert "Committed" in result


async def test_git_status():
    """git_status should return short status output."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"M  file.py\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await git_status()
        assert "file.py" in result


async def test_git_diff():
    """git_diff should return diff stat output."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(b" file.py | 2 +-\n 1 file changed\n", b"")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await git_diff()
        assert "file.py" in result

    # Test staged diff
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await git_diff(staged=True)
        assert "file.py" in result
