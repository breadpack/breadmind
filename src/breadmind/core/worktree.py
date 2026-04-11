"""Git worktree manager for agent isolation."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from breadmind.utils.helpers import generate_short_id

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""
    id: str
    path: str
    branch: str
    base_branch: str
    agent_id: str
    created_at: float = field(default_factory=lambda: __import__('time').monotonic())
    has_changes: bool = False


class WorktreeManager:
    """Manages git worktrees for agent isolation.

    Each agent can work in an isolated worktree, preventing
    concurrent modifications to the same files.
    """

    def __init__(self, repo_path: str | None = None,
                 worktree_dir: str | None = None) -> None:
        self._repo_path = repo_path or os.getcwd()
        self._worktree_dir = worktree_dir or os.path.join(self._repo_path, ".breadmind-worktrees")
        self._worktrees: dict[str, WorktreeInfo] = {}

    async def create(self, agent_id: str, base_branch: str = "HEAD") -> WorktreeInfo:
        """Create a new worktree for an agent.

        Creates a new branch and worktree directory.
        """
        wt_id = f"wt_{generate_short_id()}"
        branch_name = f"breadmind/{agent_id}/{wt_id}"
        wt_path = os.path.join(self._worktree_dir, wt_id)

        os.makedirs(self._worktree_dir, exist_ok=True)

        # Create worktree with new branch
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch_name, wt_path, base_branch,
            cwd=self._repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {stderr.decode()}")

        info = WorktreeInfo(
            id=wt_id, path=wt_path, branch=branch_name,
            base_branch=base_branch, agent_id=agent_id,
        )
        self._worktrees[wt_id] = info
        logger.info("Created worktree %s at %s for agent %s", wt_id, wt_path, agent_id)
        return info

    async def remove(self, wt_id: str, force: bool = False) -> bool:
        """Remove a worktree. If force=False, only removes if no changes."""
        info = self._worktrees.get(wt_id)
        if info is None:
            return False

        if not force:
            has_changes = await self._check_changes(info.path)
            if has_changes:
                info.has_changes = True
                logger.warning("Worktree %s has uncommitted changes, not removing", wt_id)
                return False

        # Remove worktree
        args = ["git", "worktree", "remove", info.path]
        if force:
            args.append("--force")
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self._repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Delete branch if no changes
        if not info.has_changes:
            await self._delete_branch(info.branch)

        del self._worktrees[wt_id]
        return True

    async def cleanup_all(self, force: bool = False) -> int:
        """Remove all worktrees. Returns count of removed."""
        removed = 0
        for wt_id in list(self._worktrees.keys()):
            if await self.remove(wt_id, force=force):
                removed += 1
        return removed

    async def _check_changes(self, path: str) -> bool:
        """Check if worktree has uncommitted changes."""
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            cwd=path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return bool(stdout.strip())

    async def _delete_branch(self, branch: str) -> None:
        """Delete a branch."""
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "-D", branch,
            cwd=self._repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    def get_worktree(self, wt_id: str) -> WorktreeInfo | None:
        return self._worktrees.get(wt_id)

    def get_agent_worktree(self, agent_id: str) -> WorktreeInfo | None:
        """Get the worktree for a specific agent."""
        for info in self._worktrees.values():
            if info.agent_id == agent_id:
                return info
        return None

    def list_worktrees(self) -> list[WorktreeInfo]:
        return list(self._worktrees.values())
