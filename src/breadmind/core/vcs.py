"""Abstract version control operations supporting Git, Jujutsu, and Sapling."""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class VCSType(str, Enum):
    GIT = "git"
    JUJUTSU = "jj"
    SAPLING = "sl"


@dataclass
class VCSStatus:
    """Parsed VCS status output."""

    modified: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    branch: str = ""


@dataclass
class VCSCommit:
    """A single VCS commit."""

    hash: str
    message: str
    author: str
    date: str


class VCSBackend(ABC):
    """Abstract VCS backend."""

    @abstractmethod
    async def status(self, cwd: Path) -> VCSStatus: ...

    @abstractmethod
    async def commit(
        self, cwd: Path, message: str, files: list[str] | None = None
    ) -> str: ...

    @abstractmethod
    async def diff(self, cwd: Path, staged: bool = False) -> str: ...

    @abstractmethod
    async def log(self, cwd: Path, limit: int = 10) -> list[VCSCommit]: ...

    @abstractmethod
    async def current_branch(self, cwd: Path) -> str: ...

    async def _run(self, cmd: list[str], cwd: Path) -> str:
        """Run a subprocess command and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command {' '.join(cmd)} failed (rc={proc.returncode}): "
                f"{stderr.decode('utf-8', errors='replace').strip()}"
            )
        return stdout.decode("utf-8", errors="replace")


class GitBackend(VCSBackend):
    """Git implementation."""

    async def status(self, cwd: Path) -> VCSStatus:
        out = await self._run(["git", "status", "--porcelain=v1"], cwd)
        result = VCSStatus()
        result.branch = await self.current_branch(cwd)
        for line in out.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            filepath = line[3:].strip().strip('"')
            if code in ("M ", " M", "MM"):
                result.modified.append(filepath)
            elif code in ("A ", "AM"):
                result.added.append(filepath)
            elif code in ("D ", " D"):
                result.deleted.append(filepath)
            elif code == "??":
                result.untracked.append(filepath)
        return result

    async def commit(
        self, cwd: Path, message: str, files: list[str] | None = None
    ) -> str:
        if files:
            await self._run(["git", "add", "--"] + files, cwd)
        out = await self._run(["git", "commit", "-m", message], cwd)
        # Extract commit hash from output
        for line in out.splitlines():
            if line.startswith("["):
                # e.g., "[main abc1234] message"
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].rstrip("]")
        return out.strip()

    async def diff(self, cwd: Path, staged: bool = False) -> str:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        return await self._run(cmd, cwd)

    async def log(self, cwd: Path, limit: int = 10) -> list[VCSCommit]:
        fmt = "%H%n%s%n%an%n%ai%n---"
        out = await self._run(
            ["git", "log", f"-{limit}", f"--format={fmt}"], cwd
        )
        commits: list[VCSCommit] = []
        entries = out.strip().split("---\n")
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("\n", 3)
            if len(parts) >= 4:
                commits.append(
                    VCSCommit(
                        hash=parts[0],
                        message=parts[1],
                        author=parts[2],
                        date=parts[3],
                    )
                )
        return commits

    async def current_branch(self, cwd: Path) -> str:
        out = await self._run(["git", "branch", "--show-current"], cwd)
        return out.strip()


class JujutsuBackend(VCSBackend):
    """Jujutsu (jj) implementation."""

    async def status(self, cwd: Path) -> VCSStatus:
        out = await self._run(["jj", "status"], cwd)
        result = VCSStatus()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("M "):
                result.modified.append(line[2:].strip())
            elif line.startswith("A "):
                result.added.append(line[2:].strip())
            elif line.startswith("D "):
                result.deleted.append(line[2:].strip())
        return result

    async def commit(
        self, cwd: Path, message: str, files: list[str] | None = None
    ) -> str:
        cmd = ["jj", "commit", "-m", message]
        out = await self._run(cmd, cwd)
        return out.strip()

    async def diff(self, cwd: Path, staged: bool = False) -> str:
        return await self._run(["jj", "diff"], cwd)

    async def log(self, cwd: Path, limit: int = 10) -> list[VCSCommit]:
        out = await self._run(
            [
                "jj",
                "log",
                f"-n{limit}",
                "--no-graph",
                "-T",
                'commit_id ++ "\\n" ++ description.first_line() ++ "\\n" ++ '
                'author.name() ++ "\\n" ++ author.timestamp() ++ "\\n---\\n"',
            ],
            cwd,
        )
        commits: list[VCSCommit] = []
        entries = out.strip().split("---\n")
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("\n", 3)
            if len(parts) >= 4:
                commits.append(
                    VCSCommit(
                        hash=parts[0],
                        message=parts[1],
                        author=parts[2],
                        date=parts[3],
                    )
                )
        return commits

    async def current_branch(self, cwd: Path) -> str:
        # Jujutsu doesn't have branches in the same way
        out = await self._run(["jj", "branch", "list"], cwd)
        for line in out.splitlines():
            if "*" in line:
                return line.replace("*", "").strip().split()[0]
        return ""


class SaplingBackend(VCSBackend):
    """Sapling (sl) implementation."""

    async def status(self, cwd: Path) -> VCSStatus:
        out = await self._run(["sl", "status"], cwd)
        result = VCSStatus()
        for line in out.splitlines():
            if len(line) < 3:
                continue
            code = line[0]
            filepath = line[2:].strip()
            if code == "M":
                result.modified.append(filepath)
            elif code == "A":
                result.added.append(filepath)
            elif code == "R":
                result.deleted.append(filepath)
            elif code == "?":
                result.untracked.append(filepath)
        return result

    async def commit(
        self, cwd: Path, message: str, files: list[str] | None = None
    ) -> str:
        cmd = ["sl", "commit", "-m", message]
        if files:
            cmd.extend(files)
        out = await self._run(cmd, cwd)
        return out.strip()

    async def diff(self, cwd: Path, staged: bool = False) -> str:
        return await self._run(["sl", "diff"], cwd)

    async def log(self, cwd: Path, limit: int = 10) -> list[VCSCommit]:
        out = await self._run(
            [
                "sl",
                "log",
                f"-l{limit}",
                "--template",
                "{node}\\n{desc|firstline}\\n{author|person}\\n{date|isodate}\\n---\\n",
            ],
            cwd,
        )
        commits: list[VCSCommit] = []
        entries = out.strip().split("---\n")
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("\n", 3)
            if len(parts) >= 4:
                commits.append(
                    VCSCommit(
                        hash=parts[0],
                        message=parts[1],
                        author=parts[2],
                        date=parts[3],
                    )
                )
        return commits

    async def current_branch(self, cwd: Path) -> str:
        out = await self._run(["sl", "branch"], cwd)
        return out.strip()


_BACKENDS: dict[VCSType, type[VCSBackend]] = {
    VCSType.GIT: GitBackend,
    VCSType.JUJUTSU: JujutsuBackend,
    VCSType.SAPLING: SaplingBackend,
}


class VCSManager:
    """Auto-detects and manages VCS operations.

    Checks for .git, .jj, .sl directories.
    """

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._backend: VCSBackend | None = None
        self._type: VCSType | None = None

    def detect(self) -> VCSType | None:
        """Auto-detect VCS type from project root."""
        checks = [
            (VCSType.GIT, ".git"),
            (VCSType.JUJUTSU, ".jj"),
            (VCSType.SAPLING, ".sl"),
        ]
        for vcs_type, marker in checks:
            if (self._root / marker).exists():
                self._type = vcs_type
                self._backend = _BACKENDS[vcs_type]()
                return vcs_type
        return None

    @property
    def backend(self) -> VCSBackend:
        """Get the detected VCS backend. Raises if none detected."""
        if self._backend is None:
            detected = self.detect()
            if self._backend is None:
                raise RuntimeError(
                    f"No VCS detected in {self._root}. "
                    "Looked for .git, .jj, .sl directories."
                )
        return self._backend

    @property
    def vcs_type(self) -> VCSType | None:
        """Get the detected VCS type."""
        if self._type is None:
            self.detect()
        return self._type
