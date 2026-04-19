"""`breadmind update` — detect install mode and apply the right upgrade.

The updater auto-detects how BreadMind is installed and picks the matching
upgrade path, so it works for developers (editable install) and users
(PyPI/git install) alike:

- editable  → `git pull --ff-only` in the project dir, then `pip install -e`
- git       → `pip install --upgrade git+https://github.com/...`
- pypi      → `pip install --upgrade breadmind`

On Windows, if the BreadMind service is registered via NSSM and running,
the service is restarted after a successful update (unless --no-restart).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import aiohttp

InstallMode = Literal["editable", "git", "pypi", "unknown"]


GITHUB_RELEASES_URL = "https://api.github.com/repos/breadpack/breadmind/releases/latest"
GIT_INSTALL_URL = "git+https://github.com/breadpack/breadmind.git"
SERVICE_NAME = "BreadMind"


@dataclass
class InstallInfo:
    mode: InstallMode
    editable_path: Path | None = None
    git_url: str | None = None


# --- Detection -------------------------------------------------------------

def get_current_version() -> str:
    try:
        from importlib.metadata import version
        return version("breadmind")
    except Exception:
        return "0.0.0"


def detect_install_mode() -> InstallInfo:
    """Read pip's `direct_url.json` metadata to tell how we were installed."""
    try:
        from importlib.metadata import distribution
        dist = distribution("breadmind")
        raw = dist.read_text("direct_url.json")
    except Exception:
        return InstallInfo(mode="pypi")  # safe default for end-users

    if not raw:
        return InstallInfo(mode="pypi")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return InstallInfo(mode="unknown")

    url = data.get("url", "")
    dir_info = data.get("dir_info") or {}
    vcs_info = data.get("vcs_info") or {}

    if dir_info.get("editable") and url.startswith("file:"):
        parsed = urlparse(url)
        # file:///D:/Projects/breadmind → D:/Projects/breadmind
        path_str = unquote(parsed.path)
        if os.name == "nt" and path_str.startswith("/"):
            path_str = path_str.lstrip("/")
        return InstallInfo(mode="editable", editable_path=Path(path_str))

    if vcs_info:
        return InstallInfo(mode="git", git_url=url)

    # A local (non-editable) file install falls through to unknown.
    return InstallInfo(mode="unknown")


# --- Version check ---------------------------------------------------------

async def fetch_latest_version(session: aiohttp.ClientSession | None = None) -> str | None:
    """Latest stable release tag (strip leading v), or None on failure."""
    close_after = session is None
    s = session or aiohttp.ClientSession()
    try:
        async with s.get(GITHUB_RELEASES_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None
    finally:
        if close_after:
            await s.close()

    tag = (data.get("tag_name") or "").lstrip("v").strip()
    return tag or None


def is_newer(latest: str, current: str) -> bool:
    """True if `latest` is strictly greater than `current` using PEP 440 order."""
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception:
        # Fallback: lexicographic. Not ideal but avoids import-time failures.
        return latest != current and latest > current


# --- Upgrade strategies ----------------------------------------------------

async def _stream_subprocess(*args: str, cwd: str | None = None) -> int:
    """Run a subprocess and stream its combined output line-by-line."""
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for line in proc.stdout:
        sys.stdout.write("    " + line.decode("utf-8", errors="replace"))
        sys.stdout.flush()
    return await proc.wait()


async def update_editable(project_dir: Path) -> bool:
    """git pull + re-install editable to refresh dependency metadata."""
    if not (project_dir / ".git").exists():
        print(f"  Editable path {project_dir} is not a git checkout — skipping git pull.")
        return False

    print(f"  git pull in {project_dir}")
    rc = await _stream_subprocess("git", "-C", str(project_dir), "pull", "--ff-only")
    if rc != 0:
        return False

    print("  Refreshing editable install")
    rc = await _stream_subprocess(sys.executable, "-m", "pip", "install", "-e", str(project_dir))
    return rc == 0


async def update_from_git() -> bool:
    print("  pip install --upgrade from git")
    rc = await _stream_subprocess(sys.executable, "-m", "pip", "install", "--upgrade", GIT_INSTALL_URL)
    return rc == 0


async def update_from_pypi() -> bool:
    print("  pip install --upgrade from PyPI")
    rc = await _stream_subprocess(sys.executable, "-m", "pip", "install", "--upgrade", "breadmind")
    return rc == 0


# --- Service restart (Windows) --------------------------------------------

def _nssm_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    candidate = Path(appdata) / "breadmind" / "bin" / "nssm.exe"
    return candidate if candidate.exists() else None


async def _service_exists() -> bool:
    if os.name != "nt":
        return False
    proc = await asyncio.create_subprocess_exec(
        "sc", "query", SERVICE_NAME,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    rc = await proc.wait()
    return rc == 0


async def restart_service_if_running() -> None:
    if os.name != "nt":
        return
    if not await _service_exists():
        return
    from breadmind.cli.service import is_admin
    if not is_admin():
        print("  BreadMind service is registered but restart needs Administrator rights.")
        print("  Run from an elevated shell: breadmind service restart")
        return
    nssm = _nssm_path()
    if nssm is None:
        print("  BreadMind service detected, but NSSM not found — skipping restart.")
        return
    print("  Restarting BreadMind service via NSSM")
    rc = await _stream_subprocess(str(nssm), "restart", SERVICE_NAME)
    if rc == 0:
        print("  Service restarted.")
    else:
        print("  Service restart returned non-zero — check logs in %APPDATA%\\breadmind")
        print("  Or retry: breadmind service restart (from elevated shell)")


# --- Orchestrator ---------------------------------------------------------

async def run_update(*, check_only: bool = False, no_restart: bool = False) -> int:
    """Main entry invoked by `breadmind update`. Returns process-style rc."""
    current = get_current_version()
    print(f"  Current version: v{current}")
    print("  Checking for updates...")

    latest = await fetch_latest_version()
    if latest is None:
        print("  Could not reach GitHub to check for the latest release.")
        return 1

    if not is_newer(latest, current):
        print(f"  Already up to date (v{current})")
        return 0

    print(f"  Update available: v{current} -> v{latest}")
    if check_only:
        return 0

    info = detect_install_mode()
    print(f"  Install mode: {info.mode}" + (f" ({info.editable_path})" if info.editable_path else ""))

    if info.mode == "editable" and info.editable_path:
        ok = await update_editable(info.editable_path)
    elif info.mode == "git":
        ok = await update_from_git()
    elif info.mode == "pypi":
        ok = await update_from_pypi()
    else:
        # Unknown mode → safest bet is PyPI, then git.
        ok = await update_from_pypi() or await update_from_git()

    if not ok:
        print("  Update failed.")
        return 2

    new_version = get_current_version()
    print(f"  Updated to v{new_version}")

    if no_restart:
        print("  --no-restart given, not restarting the service.")
    else:
        await restart_service_if_running()

    return 0
