"""`breadmind doctor` - diagnostics with optional auto-fix.

`doctor` runs a battery of checks. With `--fix` it also repairs issues
that have a remediation attached. Non-sensitive fixes apply automatically;
sensitive ones (admin required, modifies shared files, etc.) require user
confirmation. `--yes` auto-accepts sensitive fixes. `--deep` enables slow
checks that actually reach out to the network/DB.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from breadmind.cli.ui import get_ui


FixApply = Callable[[], Awaitable[tuple[bool, str]]]


@dataclass
class Fix:
    """A repair action attached to a CheckResult.

    - `apply`: async callable that performs the fix in-process.
    - `elevation_command`: copy-pasteable shell command when we can't fix
      from the current process (e.g. admin required) - shown to the user.
    At least one of `apply` or `elevation_command` must be set.
    """
    description: str
    sensitive: bool = False
    apply: FixApply | None = None
    elevation_command: str | None = None


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str = ""
    fix: Fix | None = None


# --- Entry point -----------------------------------------------------------

async def run_doctor(args) -> None:
    ui = get_ui()
    ui.panel("BreadMind Doctor", "Running system diagnostics...")

    deep = bool(getattr(args, "deep", False))
    results: list[CheckResult] = []

    with ui.spinner("Checking configuration"):
        results.append(check_config())
        results.append(check_config_schema())
    with ui.spinner("Checking Python version"):
        results.append(check_python())
    with ui.spinner("Checking dependencies"):
        results.extend(check_dependencies())
    with ui.spinner("Checking LLM providers"):
        results.extend(await check_providers())
    with ui.spinner("Checking database"):
        results.append(await check_database(deep=deep))
    with ui.spinner("Checking MCP servers"):
        results.extend(await check_mcp_servers())
    with ui.spinner("Checking Windows service"):
        results.append(await check_service_state())
        results.append(check_service_python_module())
    with ui.spinner("Checking disk space"):
        results.append(check_disk_space())

    _print_results_table(ui, results)

    if getattr(args, "fix", False):
        await _run_fixes(
            ui, results,
            auto_accept=bool(getattr(args, "yes", False)),
            elevated=bool(getattr(args, "elevated", False)),
        )


def _print_results_table(ui, results: list[CheckResult]) -> None:
    ok = warn = fail = skip = 0
    rows: list[list[str]] = []
    for r in results:
        icon = {"ok": "[ok]", "warn": "[!]", "fail": "[x]", "skip": "[-]"}[r.status]
        marker = " (fix)" if r.fix is not None else ""
        rows.append([icon, r.name, (r.detail + marker) if marker else r.detail])
        if r.status == "ok":
            ok += 1
        elif r.status == "warn":
            warn += 1
        elif r.status == "fail":
            fail += 1
        else:
            skip += 1

    ui.table(["Status", "Check", "Detail"], rows)

    summary = f"{ok} ok, {warn} warnings, {fail} failures, {skip} skipped"
    if fail > 0:
        ui.error(f"Summary: {summary}")
        if any(r.fix is not None for r in results):
            ui.warning("Run `breadmind doctor --fix` to apply suggested fixes.")
    elif warn > 0:
        ui.warning(f"Summary: {summary}")
    else:
        ui.success(f"Summary: {summary}")


# --- Fix flow --------------------------------------------------------------

def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    """Returns `default` in non-interactive environments."""
    if not _is_interactive():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


async def _run_fixes(
    ui, results: list[CheckResult], *, auto_accept: bool, elevated: bool = False,
) -> None:
    fixable = [r for r in results if r.fix is not None]
    if not fixable:
        return
    ui.panel("Auto-fix", f"{len(fixable)} fixable issue(s)")

    applied = skipped = failed = 0
    for r in fixable:
        fix = r.fix
        assert fix is not None
        print()
        print(f"- {r.name}: {r.detail}")
        print(f"    {fix.description}")

        # Case 1: only an elevation_command is available - cannot apply in-process.
        if fix.apply is None:
            if not fix.elevation_command:
                skipped += 1
                continue
            if elevated:
                print(f"    Launching elevated: {fix.elevation_command}")
                ok, message = await run_elevation_command(fix.elevation_command)
                if ok:
                    applied += 1
                    ui.success(f"    elevated command completed")
                else:
                    failed += 1
                    ui.error(f"    elevated command failed: {message}")
            else:
                print("    Run manually (or re-run doctor with --elevated):")
                print(f"      {fix.elevation_command}")
                skipped += 1
            continue

        # Case 2: in-process fix. Prompt only for sensitive ones.
        if fix.sensitive and not auto_accept:
            if not _ask_yes_no("    Apply this fix?", default=False):
                skipped += 1
                continue

        try:
            ok, message = await fix.apply()
        except Exception as exc:
            failed += 1
            ui.error(f"    Fix error: {exc}")
            continue
        if ok:
            applied += 1
            ui.success(f"    {message}")
        else:
            failed += 1
            ui.error(f"    {message}")

    ui.info(f"Fix summary: {applied} applied, {skipped} skipped, {failed} failed")


async def run_elevation_command(command: str) -> tuple[bool, str]:
    """Synchronously execute an elevation_command.

    On Windows, if the command is a `Start-Process ... -Verb RunAs ...`
    snippet we insert `-Wait` so this call blocks until the elevated
    process exits. Other commands are passed through unchanged and run
    via powershell.exe under the current user.

    On POSIX, the command is passed to the user's shell. `sudo` inside
    the command handles elevation interactively.
    """
    if os.name == "nt":
        cmd = command
        # Make Start-Process block by adding -Wait when missing.
        if ("Start-Process" in cmd and "-Verb RunAs" in cmd
                and "-Wait" not in cmd):
            cmd = cmd.replace("-Verb RunAs", "-Verb RunAs -Wait", 1)
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe", "-NoProfile", "-Command", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    out, _ = await proc.communicate()
    output = out.decode("utf-8", errors="replace")
    if output.strip():
        for line in output.splitlines()[-5:]:
            print(f"      {line}")
    return (proc.returncode == 0, output[-200:] if output else "")


# --- Checks ----------------------------------------------------------------

def check_config() -> CheckResult:
    try:
        from breadmind.config import get_default_config_dir, load_config
        config_dir = get_default_config_dir()
        config_path = os.path.join(config_dir, "config.yaml")
        if not os.path.exists(config_path):
            if os.path.exists("config/config.yaml"):
                return CheckResult("Config", "ok", "./config/config.yaml")
            return CheckResult(
                "Config", "fail", f"Not found: {config_path}",
                fix=Fix(
                    description="Run `breadmind setup` to create a config interactively",
                    sensitive=True,
                    elevation_command="breadmind setup",
                ),
            )
        load_config(config_dir)
        return CheckResult("Config", "ok", config_path)
    except Exception as e:
        return CheckResult("Config", "fail", str(e))


def check_config_schema() -> CheckResult:
    """Detect deprecated LLM config keys (e.g. `fallback_chain`)."""
    try:
        import yaml
        from breadmind.config import get_default_config_dir
        config_path = Path(get_default_config_dir()) / "config.yaml"
        if not config_path.exists():
            return CheckResult("Config schema", "skip", "config not found")
        data: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return CheckResult("Config schema", "skip", "config is not a mapping")
        llm = data.get("llm") or {}
        if not isinstance(llm, dict):
            return CheckResult("Config schema", "skip", "llm section is not a mapping")

        deprecated: dict[str, Any] = {}
        if "fallback_chain" in llm:
            deprecated["fallback_chain"] = llm["fallback_chain"]
        if not deprecated:
            return CheckResult("Config schema", "ok", "up to date")

        async def _apply() -> tuple[bool, str]:
            new_llm = dict(llm)
            chain = new_llm.pop("fallback_chain", None)
            if isinstance(chain, list) and chain:
                current = new_llm.get("default_provider")
                fb = next((p for p in chain if p != current), chain[0])
                new_llm.setdefault("fallback_provider", fb)
            new_data = dict(data)
            new_data["llm"] = new_llm
            config_path.write_text(
                yaml.safe_dump(new_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            return (True, f"migrated → fallback_provider={new_llm.get('fallback_provider', '-')}")

        return CheckResult(
            "Config schema", "warn",
            f"deprecated: {', '.join(deprecated)}",
            fix=Fix(
                description="Rewrite config.yaml with current schema",
                sensitive=False,
                apply=_apply,
            ),
        )
    except Exception as e:
        return CheckResult("Config schema", "skip", str(e)[:60])


def check_python() -> CheckResult:
    ver = sys.version_info
    major, minor, micro = ver[0], ver[1], ver[2]
    if ver >= (3, 12):
        return CheckResult("Python", "ok", f"{major}.{minor}.{micro}")
    elif ver >= (3, 10):
        return CheckResult("Python", "warn", f"{major}.{minor} (3.12+ recommended)")
    return CheckResult("Python", "fail", f"{major}.{minor} (3.12+ required)")


def check_dependencies() -> list[CheckResult]:
    results = []
    deps = {
        "anthropic": ("Anthropic SDK", False),
        "asyncpg": ("PostgreSQL driver", True),
        "aiohttp": ("HTTP client", False),
        "fastapi": ("Web framework", False),
        "uvicorn": ("ASGI server", False),
    }
    for pkg, (name, optional) in deps.items():
        try:
            __import__(pkg)
            results.append(CheckResult(name, "ok", "installed"))
        except ImportError:
            fix = Fix(
                description=f"Install missing package `{pkg}`",
                sensitive=True,
                elevation_command=f"pip install {pkg}",
            )
            if optional:
                results.append(CheckResult(name, "skip", "not installed (optional)", fix=fix))
            else:
                results.append(CheckResult(name, "fail", "not installed", fix=fix))
    return results


async def check_providers() -> list[CheckResult]:
    results = []
    try:
        from breadmind.llm.factory import get_provider_options
        for opt in get_provider_options():
            env_key = opt.get("env_key")
            name = opt["name"]
            if not env_key:
                results.append(CheckResult(f"LLM: {name}", "ok", "no key needed"))
                continue
            key = os.environ.get(env_key, "")
            if not key:
                try:
                    from breadmind.config import get_default_config_dir
                    env_path = os.path.join(get_default_config_dir(), ".env")
                    if os.path.exists(env_path):
                        for line in Path(env_path).read_text().splitlines():
                            if line.startswith(f"{env_key}="):
                                key = line.split("=", 1)[1].strip()
                                break
                except Exception:
                    pass
            if key:
                masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
                results.append(CheckResult(f"LLM: {name}", "ok", f"key={masked}"))
            else:
                results.append(CheckResult(f"LLM: {name}", "skip", f"{env_key} not set"))
    except Exception as e:
        results.append(CheckResult("LLM Providers", "fail", str(e)))
    return results


async def check_database(*, deep: bool = False) -> CheckResult:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        try:
            from breadmind.config import get_default_config_dir
            env_path = os.path.join(get_default_config_dir(), ".env")
            if os.path.exists(env_path):
                for line in Path(env_path).read_text().splitlines():
                    if line.startswith("DATABASE_URL="):
                        dsn = line.split("=", 1)[1].strip()
        except Exception:
            pass
    if not dsn:
        return CheckResult("PostgreSQL", "skip", "DATABASE_URL not set (file-based storage)")
    try:
        import asyncpg
    except ImportError:
        return CheckResult(
            "PostgreSQL", "warn", "asyncpg not installed",
            fix=Fix(
                description="Install asyncpg",
                sensitive=True,
                elevation_command="pip install asyncpg",
            ),
        )
    if not deep:
        return CheckResult("PostgreSQL", "ok", "asyncpg installed (use --deep to actually connect)")
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        short_ver = version.split(",")[0] if version else "connected"
        return CheckResult("PostgreSQL", "ok", short_ver)
    except Exception as e:
        return CheckResult("PostgreSQL", "fail", str(e)[:80])


async def check_mcp_servers() -> list[CheckResult]:
    results = []
    try:
        from breadmind.config import get_default_config_dir, load_config
        config_dir = get_default_config_dir()
        if not os.path.exists(os.path.join(config_dir, "config.yaml")):
            if os.path.exists("config/config.yaml"):
                config_dir = "config"
            else:
                return [CheckResult("MCP Servers", "skip", "no config")]
        config = load_config(config_dir)
        servers = config.mcp.servers
        if not servers:
            return [CheckResult("MCP Servers", "skip", "none configured")]
        for name in servers:
            results.append(CheckResult(f"MCP: {name}", "ok", "configured"))
    except Exception as e:
        results.append(CheckResult("MCP Servers", "warn", str(e)[:60]))
    return results


async def check_service_state() -> CheckResult:
    """BreadMind Windows service: registered and running?"""
    if os.name != "nt":
        return CheckResult("Windows Service", "skip", "non-Windows")
    proc = await asyncio.create_subprocess_exec(
        "sc", "query", "BreadMind",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return CheckResult(
            "Windows Service", "warn", "not registered",
            fix=Fix(
                description="Register BreadMind service via NSSM (admin)",
                sensitive=True,
                elevation_command=(
                    "Start-Process pwsh -Verb RunAs -ArgumentList '-NoProfile',"
                    "'-Command','python -m breadmind service install; Read-Host Enter'"
                ),
            ),
        )
    output = out.decode("utf-8", errors="replace")
    state = "UNKNOWN"
    for token in output.split():
        if token in ("RUNNING", "STOPPED", "PAUSED",
                     "START_PENDING", "STOP_PENDING"):
            state = token
            break
    if state == "RUNNING":
        return CheckResult("Windows Service", "ok", "RUNNING")
    if state in ("STOPPED", "PAUSED"):
        from breadmind.cli.service import is_admin
        if is_admin():
            async def _apply() -> tuple[bool, str]:
                from breadmind.cli.service import restart as svc_restart
                rc = await svc_restart()
                return (rc == 0, "service restarted" if rc == 0 else "restart failed")
            return CheckResult(
                "Windows Service", "fail", f"{state} - admin detected, can restart",
                fix=Fix(
                    description=f"Restart service (currently {state})",
                    sensitive=False,
                    apply=_apply,
                ),
            )
        return CheckResult(
            "Windows Service", "fail", f"{state} - admin required to restart",
            fix=Fix(
                description="Restart service as Administrator",
                sensitive=True,
                elevation_command=(
                    "Start-Process pwsh -Verb RunAs -ArgumentList '-NoProfile',"
                    "'-Command','python -m breadmind service restart; Read-Host Enter'"
                ),
            ),
        )
    return CheckResult("Windows Service", "warn", f"state={state}")


def _read_nssm_value(nssm: Path, key: str) -> str | None:
    """NSSM prints config values as UTF-16 LE; decode robustly."""
    try:
        result = subprocess.run(
            [str(nssm), "get", "BreadMind", key],
            capture_output=True, timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout
    for encoding in ("utf-16-le", "utf-16", "utf-8", "mbcs"):
        try:
            decoded = raw.decode(encoding, errors="strict")
            decoded = decoded.replace("\x00", "").strip()
            if decoded:
                return decoded
        except Exception:
            continue
    return None


def check_service_python_module() -> CheckResult:
    """The Python that NSSM runs the service under must have `breadmind`
    importable. When the package is installed into per-user site-packages
    but the service runs as LocalSystem, the service will crash-loop with
    `No module named breadmind`. Detect and offer an admin-level fix."""
    if os.name != "nt":
        return CheckResult("Service Python", "skip", "non-Windows")
    try:
        from breadmind.cli.service import nssm_path
    except Exception:
        return CheckResult("Service Python", "skip", "service module unavailable")
    nssm = nssm_path()
    if nssm is None:
        return CheckResult("Service Python", "skip", "NSSM not installed")

    python_path = _read_nssm_value(nssm, "Application")
    if not python_path or not Path(python_path).exists():
        return CheckResult("Service Python", "skip",
                           f"cannot read NSSM Application ({python_path!r})")

    try:
        proc = subprocess.run(
            [python_path, "-c", "import breadmind"],
            capture_output=True, timeout=10,
        )
    except Exception as exc:
        return CheckResult("Service Python", "fail", str(exc)[:80])
    if proc.returncode == 0:
        return CheckResult("Service Python", "ok",
                           f"{Path(python_path).name}: breadmind importable")

    # Try to derive the editable project dir to point the admin install at.
    project_hint = ""
    try:
        from breadmind.cli.updater import detect_install_mode
        info = detect_install_mode()
        if info.editable_path:
            project_hint = f' "{info.editable_path}"'
    except Exception:
        pass
    elevation = (
        "Start-Process pwsh -Verb RunAs -ArgumentList '-NoProfile','-Command',"
        f"'& \"{python_path}\" -m pip install -e{project_hint or ' breadmind'}; Read-Host Enter'"
    )
    return CheckResult(
        "Service Python", "fail",
        f"{Path(python_path).name} cannot import breadmind (service will crash-loop)",
        fix=Fix(
            description="Install breadmind into the service's Python (admin)",
            sensitive=True,
            elevation_command=elevation,
        ),
    )


def check_disk_space() -> CheckResult:
    import shutil
    try:
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        if free_gb > 5:
            return CheckResult("Disk Space", "ok", f"{free_gb:.1f} GB free")
        elif free_gb > 1:
            return CheckResult("Disk Space", "warn", f"{free_gb:.1f} GB free (low)")
        return CheckResult("Disk Space", "fail", f"{free_gb:.1f} GB free (critical)")
    except Exception:
        return CheckResult("Disk Space", "skip", "unable to check")
