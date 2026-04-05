"""Tests for team integration with worktree isolation."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from breadmind.core.agent_team import AgentTeam, TeammateConfig
from breadmind.core.team_integration import IsolatedTeamRunner


@pytest.fixture
def team():
    t = AgentTeam(name="test-team")
    t.add_teammate(TeammateConfig(agent_id="agent_a", name="A", role="impl"))
    t.add_teammate(TeammateConfig(agent_id="agent_b", name="B", role="review"))
    return t


@pytest.fixture
def mock_worktree_mgr():
    mgr = MagicMock()

    async def mock_create(agent_id):
        wt = MagicMock()
        wt.path = f"/tmp/worktrees/{agent_id}"
        return wt

    mgr.create = mock_create
    mgr.cleanup_all = AsyncMock(return_value=2)
    return mgr


async def test_isolated_team_creates_worktrees(team, mock_worktree_mgr):
    runner = IsolatedTeamRunner(team, mock_worktree_mgr)
    handler = AsyncMock(return_value="done")

    # Patch start to capture the wrapped handler
    original_start = team.start
    captured_handler = None

    async def capture_start(h):
        nonlocal captured_handler
        captured_handler = h

    team.start = capture_start
    await runner.start_isolated(handler)

    # Verify worktrees were created
    assert "agent_a" in runner._worktrees
    assert "agent_b" in runner._worktrees
    assert runner._worktrees["agent_a"] == "/tmp/worktrees/agent_a"


async def test_cleanup_calls_worktree_cleanup(team, mock_worktree_mgr):
    runner = IsolatedTeamRunner(team, mock_worktree_mgr)
    result = await runner.cleanup(force=True)
    assert result == 2
    mock_worktree_mgr.cleanup_all.assert_called_once_with(force=True)


async def test_workdir_passed_in_metadata(team, mock_worktree_mgr):
    runner = IsolatedTeamRunner(team, mock_worktree_mgr)
    handler = AsyncMock(return_value="done")

    captured_handler = None

    async def capture_start(h):
        nonlocal captured_handler
        captured_handler = h

    team.start = capture_start
    await runner.start_isolated(handler)

    # Simulate calling the wrapped handler
    mock_task = MagicMock()
    mock_task.metadata = {}
    mock_mailbox = MagicMock()

    await captured_handler("agent_a", mock_task, mock_mailbox)
    assert mock_task.metadata["workdir"] == "/tmp/worktrees/agent_a"
    handler.assert_called_once_with("agent_a", mock_task, mock_mailbox)
