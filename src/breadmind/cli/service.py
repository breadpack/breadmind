"""`breadmind service` — Windows service (NSSM) management.

Handles registration, start/stop/restart/remove, and status of the
BreadMind Windows service. Most actions need Administrator rights;
`status` works from a normal user shell so diagnostics are always
available.

When an action requires elevation and isn't running with it, we print
the exact command to re-run under Administrator rather than silently
self-elevating (which would spawn a new window and lose stdout).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


SERVICE_NAME = "BreadMind"


def is_admin() -> bool:
    """True when the current process has elevated / root privileges."""
    if os.name != "nt":
        try:
            return os.geteuid() == 0  # type: ignore[attr-defined]
        except AttributeError:
            return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except Exception:
        return False


def nssm_path() -> Path | None:
    """Path to the NSSM binary that the installer drops alongside config."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    candidate = Path(appdata) / "breadmind" / "bin" / "nssm.exe"
    return candidate if candidate.exists() else None


def default_config_dir() -> str:
    appdata = os.environ.get("APPDATA", "")
    return str(Path(appdata) / "breadmind") if appdata else ""


def _print_admin_instructions(command: str) -> None:
    print(f"  Administrator rights are required for `breadmind service {command}`.")
    print("  Run from an elevated PowerShell / Command Prompt, or:")
    print(
        f"    Start-Process pwsh -Verb RunAs -ArgumentList "
        f"'-NoProfile','-Command','python -m breadmind service {command}; Read-Host Enter'"
    )


async def _run(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace")


def _parse_sc_state(output: str) -> str:
    """Extract the STATE token from a localized `sc query` response."""
    known = {"RUNNING", "STOPPED", "PAUSED", "START_PENDING", "STOP_PENDING",
             "CONTINUE_PENDING", "PAUSE_PENDING"}
    for line in output.splitlines():
        for token in line.split():
            if token in known:
                return token
    return "UNKNOWN"


# --- Actions ---------------------------------------------------------------

async def status() -> int:
    if os.name != "nt":
        print("  `breadmind service` currently supports Windows only.")
        return 1
    rc, out = await _run("sc", "query", SERVICE_NAME)
    if rc != 0:
        print(f"  Service '{SERVICE_NAME}' is not registered.")
        print("  Run `breadmind service install` as Administrator to register it.")
        return 1
    print(f"  Service: {SERVICE_NAME}")
    print(f"  State:   {_parse_sc_state(out)}")
    # Show bound port if running
    rc, cfg_out = await _run("sc", "qc", SERVICE_NAME)
    for line in cfg_out.splitlines():
        stripped = line.strip()
        if stripped.startswith("START_TYPE"):
            print(f"  {stripped}")
        elif stripped.startswith("BINARY_PATH_NAME"):
            print(f"  {stripped}")
    return 0


async def install(config_dir: str | None = None) -> int:
    if os.name != "nt":
        print("  Windows only.")
        return 1
    if not is_admin():
        _print_admin_instructions("install")
        return 1
    nssm = nssm_path()
    if nssm is None:
        print("  NSSM not found at %APPDATA%\\breadmind\\bin\\nssm.exe")
        print("  Run deploy/install/install.ps1 to download NSSM, or install it manually.")
        return 1

    cfg = config_dir or default_config_dir()
    python = sys.executable
    log = str(Path(cfg) / "breadmind.log")
    err = str(Path(cfg) / "breadmind.err")

    # Wipe any prior partial registration; ignore failures (may not exist).
    await _run(str(nssm), "remove", SERVICE_NAME, "confirm")

    rc, out = await _run(
        str(nssm), "install", SERVICE_NAME, python,
        "-m", "breadmind", "web", "--config-dir", cfg,
    )
    if rc != 0:
        print(f"  nssm install failed:\n{out}")
        return rc

    for key, value in (
        ("AppDirectory", cfg),
        ("Description", "BreadMind AI Infrastructure Agent"),
        ("Start", "SERVICE_AUTO_START"),
        ("AppEnvironmentExtra", "PYTHONUNBUFFERED=1"),
        ("AppStdout", log),
        ("AppStderr", err),
    ):
        await _run(str(nssm), "set", SERVICE_NAME, key, value)

    print(f"  Registered '{SERVICE_NAME}' with AUTO_START.")
    print("  Start it now: breadmind service start")
    return 0


async def _simple_sc(verb: str, *, command_name: str) -> int:
    if os.name != "nt":
        print("  Windows only.")
        return 1
    if not is_admin():
        _print_admin_instructions(command_name)
        return 1
    rc, out = await _run("sc", verb, SERVICE_NAME)
    if rc != 0:
        print(f"  sc {verb} failed:\n{out}")
    return rc


async def start() -> int:
    rc = await _simple_sc("start", command_name="start")
    if rc == 0:
        print(f"  Service '{SERVICE_NAME}' start requested.")
    return rc


async def stop() -> int:
    rc = await _simple_sc("stop", command_name="stop")
    if rc == 0:
        print(f"  Service '{SERVICE_NAME}' stop requested.")
    return rc


async def restart() -> int:
    if os.name != "nt":
        print("  Windows only.")
        return 1
    if not is_admin():
        _print_admin_instructions("restart")
        return 1
    # sc doesn't have restart; stop then start, ignoring stop failure when already stopped.
    await _run("sc", "stop", SERVICE_NAME)
    rc, out = await _run("sc", "start", SERVICE_NAME)
    if rc != 0:
        print(f"  sc start failed:\n{out}")
        return rc
    print(f"  Service '{SERVICE_NAME}' restarted.")
    return 0


async def remove() -> int:
    if os.name != "nt":
        print("  Windows only.")
        return 1
    if not is_admin():
        _print_admin_instructions("remove")
        return 1
    nssm = nssm_path()
    if nssm is None:
        rc, out = await _run("sc", "delete", SERVICE_NAME)
    else:
        rc, out = await _run(str(nssm), "remove", SERVICE_NAME, "confirm")
    if rc != 0:
        print(f"  remove failed:\n{out}")
        return rc
    print(f"  Service '{SERVICE_NAME}' removed.")
    return 0


# --- Dispatcher ------------------------------------------------------------

async def run_service_command(args) -> int:
    action = getattr(args, "service_action", None)
    if action == "status":
        return await status()
    if action == "install":
        return await install(getattr(args, "config_dir", None))
    if action == "start":
        return await start()
    if action == "stop":
        return await stop()
    if action == "restart":
        return await restart()
    if action == "remove":
        return await remove()
    print("Usage: breadmind service <status|install|start|stop|restart|remove>")
    return 2
