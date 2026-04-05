"""Git integration tools with co-author attribution."""

import asyncio
import os

from breadmind.tools.registry import tool

# Default co-author (configurable via env)
DEFAULT_COAUTHOR = os.environ.get(
    "BREADMIND_GIT_COAUTHOR",
    "BreadMind AI <noreply@breadmind.ai>",
)


@tool(
    description="Create a git commit with optional co-author attribution",
    read_only=False,
)
async def git_commit(
    message: str,
    add_coauthor: bool = True,
    paths: str = ".",
) -> str:
    """Stage files and create a commit. Adds co-author trailer by default."""
    # Stage
    proc = await asyncio.create_subprocess_exec(
        "git",
        "add",
        *paths.split(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        return f"git add failed: {stderr.decode()}"

    # Build commit message
    full_message = message
    if add_coauthor and DEFAULT_COAUTHOR:
        full_message += f"\n\nCo-Authored-By: {DEFAULT_COAUTHOR}"

    proc = await asyncio.create_subprocess_exec(
        "git",
        "commit",
        "-m",
        full_message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return f"git commit failed: {stderr.decode()}"
    return f"Committed: {stdout.decode().strip()}"


@tool(description="Show git status", read_only=True)
async def git_status() -> str:
    """Show short git status."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "status",
        "--short",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode() or "(clean)"


@tool(description="Show git diff", read_only=True)
async def git_diff(staged: bool = False) -> str:
    """Show git diff statistics."""
    args = ["git", "diff"]
    if staged:
        args.append("--staged")
    args.append("--stat")
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode() or "(no changes)"
