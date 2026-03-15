"""BreadMind complete uninstall — removes service, config, DB data, and containers.

Usage:
    python -m breadmind.uninstall [--yes] [--keep-db] [--keep-config]
"""

import argparse
import asyncio
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from breadmind.config import get_default_config_dir


def _print(msg: str):
    print(f"  {msg}")


def _find_nssm() -> str | None:
    """Find nssm.exe in config dir or PATH."""
    config_dir = get_default_config_dir()
    nssm = Path(config_dir) / "bin" / "nssm.exe"
    if nssm.exists():
        return str(nssm)
    if shutil.which("nssm"):
        return "nssm"
    return None


def _find_breadmind_pids() -> list[int]:
    """Find running breadmind processes."""
    pids = []
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "process", "where",
                 "CommandLine like '%breadmind%' and not CommandLine like '%uninstall%'",
                 "get", "ProcessId"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines()[1:]:
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        else:
            result = subprocess.run(
                ["pgrep", "-f", "breadmind"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                pid = int(line.strip())
                if pid != os.getpid():
                    pids.append(pid)
    except Exception:
        pass
    return pids


def stop_service():
    """Stop running BreadMind processes and system services."""
    print("\n[1/6] Stopping service...")
    system = platform.system()

    # Stop system service
    if system == "Linux":
        subprocess.run(["sudo", "systemctl", "stop", "breadmind"],
                        capture_output=True, timeout=15)
        subprocess.run(["sudo", "systemctl", "disable", "breadmind"],
                        capture_output=True, timeout=10)
        _print("systemd service stopped and disabled")
    elif system == "Windows":
        # Stop and remove NSSM or sc.exe service
        nssm_path = _find_nssm()
        svc_removed = False
        if nssm_path:
            r = subprocess.run([nssm_path, "stop", "BreadMind"],
                                capture_output=True, timeout=15)
            r2 = subprocess.run([nssm_path, "remove", "BreadMind", "confirm"],
                                 capture_output=True, timeout=15)
            svc_removed = r2.returncode == 0
        if not svc_removed:
            r = subprocess.run(["sc", "stop", "BreadMind"],
                                capture_output=True, timeout=15)
            r2 = subprocess.run(["sc", "delete", "BreadMind"],
                                 capture_output=True, timeout=15)
            svc_removed = r2.returncode == 0
        if svc_removed:
            _print("Windows service stopped and removed")
        else:
            _print("Windows service removal requires admin. Run as Administrator:"
                   "\n    sc stop BreadMind && sc delete BreadMind")
    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/dev.breadpack.breadmind.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)],
                            capture_output=True, timeout=10)
            _print("launchd service unloaded")

    # Kill running processes
    pids = _find_breadmind_pids()
    if pids:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                _print(f"Stopped process PID {pid}")
            except (ProcessLookupError, PermissionError):
                pass
        _print(f"Stopped {len(pids)} process(es)")
    else:
        _print("No running processes found")


def remove_service_files():
    """Remove system service registration files."""
    print("\n[2/6] Removing service files...")
    system = platform.system()
    removed = []

    if system == "Linux":
        svc = Path("/etc/systemd/system/breadmind.service")
        if svc.exists():
            subprocess.run(["sudo", "rm", str(svc)], capture_output=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], capture_output=True)
            removed.append(str(svc))

    elif system == "Windows":
        # NSSM service already removed in stop_service, clean up bin dir
        config_dir = get_default_config_dir()
        bin_dir = Path(config_dir) / "bin"
        if bin_dir.exists():
            shutil.rmtree(bin_dir, ignore_errors=True)
            removed.append(str(bin_dir))
    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/dev.breadpack.breadmind.plist"
        if plist.exists():
            plist.unlink()
            removed.append(str(plist))

    if removed:
        for f in removed:
            _print(f"Removed: {f}")
    else:
        _print("No service files found")


def remove_config(config_dir: str):
    """Remove config directory (settings, .env, config.yaml, etc)."""
    print("\n[3/6] Removing config directory...")
    config_path = Path(config_dir)
    if config_path.exists():
        # List contents before removing
        files = list(config_path.rglob("*"))
        shutil.rmtree(config_path, ignore_errors=True)
        _print(f"Removed: {config_path} ({len(files)} files)")
    else:
        _print(f"Not found: {config_path}")

    # Also remove project-local files
    for name in [".env", "breadmind.log", "config/settings.json"]:
        p = Path(name)
        if p.exists():
            p.unlink()
            _print(f"Removed: {p}")


async def drop_database(config_dir: str):
    """Drop all BreadMind tables from the database."""
    print("\n[4/6] Cleaning database...")
    try:
        from breadmind.config import load_config
        config = load_config(config_dir)
        dsn = config.database.dsn

        import asyncpg
        conn = await asyncpg.connect(dsn)
        tables = ["settings", "mcp_servers", "audit_log",
                   "kg_relations", "kg_entities", "episodic_notes"]
        for table in tables:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            _print(f"Dropped table: {table}")
        await conn.close()
    except Exception as e:
        _print(f"Database cleanup skipped: {e}")


def remove_docker_resources():
    """Remove BreadMind Docker containers, images, and volumes."""
    print("\n[5/6] Removing Docker resources...")
    try:
        # Stop and remove containers
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "label=breadmind.type",
             "--format", "{{.ID}}"],
            capture_output=True, text=True, timeout=10,
        )
        container_ids = result.stdout.strip().splitlines()

        # Also find compose containers
        for name in ["breadmind", "breadmind-postgres"]:
            r = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={name}",
                 "--format", "{{.ID}}"],
                capture_output=True, text=True, timeout=10,
            )
            container_ids.extend(r.stdout.strip().splitlines())

        container_ids = list(set(filter(None, container_ids)))
        if container_ids:
            subprocess.run(
                ["docker", "rm", "-f"] + container_ids,
                capture_output=True, timeout=30,
            )
            _print(f"Removed {len(container_ids)} container(s)")

        # Remove images
        for img in ["breadmind/tool-runner", "breadmind"]:
            r = subprocess.run(
                ["docker", "images", img, "-q"],
                capture_output=True, text=True, timeout=10,
            )
            img_ids = list(filter(None, r.stdout.strip().splitlines()))
            if img_ids:
                subprocess.run(["docker", "rmi", "-f"] + img_ids,
                                capture_output=True, timeout=30)
                _print(f"Removed image: {img}")

        # Remove volume
        subprocess.run(
            ["docker", "volume", "rm", "-f", "breadmind_pgdata"],
            capture_output=True, timeout=10,
        )
        _print("Removed volume: breadmind_pgdata")

    except FileNotFoundError:
        _print("Docker not found, skipping")
    except Exception as e:
        _print(f"Docker cleanup error: {e}")


def remove_pip_package():
    """Uninstall the breadmind pip package."""
    print("\n[6/6] Uninstalling pip package...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "breadmind", "-y"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0:
        _print("Uninstalled breadmind package")
    else:
        _print(f"pip uninstall: {result.stderr.strip() or 'not installed'}")


def main():
    parser = argparse.ArgumentParser(description="Completely uninstall BreadMind")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--keep-db", action="store_true",
                        help="Keep database tables (don't drop)")
    parser.add_argument("--keep-config", action="store_true",
                        help="Keep config directory (.env, settings)")
    parser.add_argument("--keep-pip", action="store_true",
                        help="Keep pip package installed")
    args = parser.parse_args()

    config_dir = get_default_config_dir()

    print("=" * 50)
    print("  BreadMind Complete Uninstaller")
    print("=" * 50)
    print(f"\n  Config dir:  {config_dir}")
    print(f"  Platform:    {platform.system()}")
    print(f"  Keep DB:     {args.keep_db}")
    print(f"  Keep config: {args.keep_config}")
    print(f"  Keep pip:    {args.keep_pip}")

    if not args.yes:
        print("\n  This will permanently delete all BreadMind data.")
        answer = input("  Continue? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled.")
            return

    # 1. Stop service
    stop_service()

    # 2. Remove service files
    remove_service_files()

    # 3. Remove config
    if not args.keep_config:
        remove_config(config_dir)
    else:
        _print("Skipping config removal (--keep-config)")

    # 4. Drop database
    if not args.keep_db:
        asyncio.run(drop_database(config_dir))
    else:
        _print("Skipping database cleanup (--keep-db)")

    # 5. Docker cleanup
    remove_docker_resources()

    # 6. Pip uninstall
    if not args.keep_pip:
        remove_pip_package()
    else:
        _print("Skipping pip uninstall (--keep-pip)")

    print("\n" + "=" * 50)
    print("  BreadMind has been completely removed.")
    print("=" * 50)


if __name__ == "__main__":
    main()
