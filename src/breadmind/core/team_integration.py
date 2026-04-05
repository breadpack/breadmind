"""Integration layer connecting AgentTeam with WorktreeManager."""
from __future__ import annotations

from typing import Any, Callable, Awaitable

from breadmind.core.agent_team import AgentTeam
from breadmind.core.worktree import WorktreeManager


class IsolatedTeamRunner:
    """Runs an AgentTeam with git worktree isolation per teammate."""

    def __init__(self, team: AgentTeam,
                 worktree_mgr: WorktreeManager | None = None) -> None:
        self._team = team
        self._worktree_mgr = worktree_mgr
        self._worktrees: dict[str, str] = {}  # agent_id -> worktree_path

    async def start_isolated(self, task_handler: Callable) -> None:
        """Start team with optional worktree isolation per agent."""
        if self._worktree_mgr:
            for agent_id in list(self._team._teammates.keys()):
                wt = await self._worktree_mgr.create(agent_id)
                self._worktrees[agent_id] = wt.path

        async def wrapped_handler(agent_id, task, mailbox):
            workdir = self._worktrees.get(agent_id)
            if workdir:
                task.metadata = getattr(task, 'metadata', {}) or {}
                task.metadata["workdir"] = workdir
            return await task_handler(agent_id, task, mailbox)

        await self._team.start(wrapped_handler)

    async def cleanup(self, force: bool = False) -> int:
        if self._worktree_mgr:
            return await self._worktree_mgr.cleanup_all(force=force)
        return 0
