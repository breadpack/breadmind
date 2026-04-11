"""CLI entry point for the BreadMind Companion Agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="breadmind-companion",
        description="BreadMind Companion Agent — personal device management",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config YAML (default: ~/.config/breadmind-companion/config.yaml)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    sub = parser.add_subparsers(dest="command")

    # pair
    pair_p = sub.add_parser("pair", help="Pair with a BreadMind Commander")
    pair_p.add_argument("--token", required=True, help="Join token secret")
    pair_p.add_argument("--url", required=True, help="Commander WebSocket URL")

    # start
    start_p = sub.add_parser("start", help="Start the companion agent")
    start_p.add_argument("--daemon", action="store_true", help="Run as background daemon")

    # status
    sub.add_parser("status", help="Show companion status")

    # configure
    sub.add_parser("configure", help="Interactive capability configuration")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "pair":
        asyncio.run(_cmd_pair(args))
    elif args.command == "start":
        asyncio.run(_cmd_start(args))
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "configure":
        _cmd_configure(args)
    else:
        parser.print_help()
        sys.exit(1)


async def _cmd_pair(args: argparse.Namespace) -> None:
    from breadmind.companion.pairing import pair
    try:
        config = await pair(args.url, args.token)
        print(f"Paired successfully! Agent ID: {config.agent_id}")
        print(f"Commander: {config.commander_url}")
    except Exception as e:
        print(f"Pairing failed: {e}", file=sys.stderr)
        sys.exit(1)


async def _cmd_start(args: argparse.Namespace) -> None:
    from pathlib import Path
    from breadmind.companion.config import load_config
    from breadmind.companion.platform import detect_platform
    from breadmind.companion.runtime import CompanionRuntime
    from breadmind.companion.tools import get_all_tools

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    if not config.commander_url:
        print("No commander_url configured. Run 'pair' first.", file=sys.stderr)
        sys.exit(1)

    platform_adapter = detect_platform()
    runtime = CompanionRuntime(config=config, platform_adapter=platform_adapter)
    runtime.register_tools(get_all_tools())

    if args.daemon:
        print(f"Starting companion agent (daemon) — {config.agent_id}")
        # On Unix, could daemonize; on Windows just run in background
        # For now, run in foreground (daemon support is OS-specific)
        print("Note: --daemon runs in foreground on this platform")

    print(f"Companion agent starting: {config.agent_id}")
    print(f"Connecting to: {config.commander_url}")
    try:
        await runtime.start()
    except KeyboardInterrupt:
        await runtime.stop()
        print("\nCompanion agent stopped.")


def _cmd_status(args: argparse.Namespace) -> None:
    from pathlib import Path
    from breadmind.companion.config import load_config, _default_config_dir

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    config_dir = _default_config_dir()

    print("=== BreadMind Companion Status ===")
    print(f"  Agent ID:      {config.agent_id}")
    print(f"  Device Name:   {config.device_name}")
    print(f"  Commander URL: {config.commander_url or '(not configured)'}")
    print(f"  Config Dir:    {config_dir}")
    print(f"  Certificate:   {config.cert_path or '(none)'}")
    print(f"  Heartbeat:     {config.heartbeat_interval}s")


def _cmd_configure(args: argparse.Namespace) -> None:
    from pathlib import Path
    from breadmind.companion.config import load_config, save_config
    from breadmind.companion.security import _DEFAULT_PERMISSIONS

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    print("=== Companion Capability Configuration ===")
    print("Enable/disable tools (y/n):\n")

    capabilities = dict(config.capabilities)
    for tool_name, default in _DEFAULT_PERMISSIONS.items():
        current = capabilities.get(tool_name, default)
        label = "enabled" if current else "disabled"
        answer = input(f"  {tool_name} [{label}] (y/n/Enter=keep): ").strip().lower()
        if answer == "y":
            capabilities[tool_name] = True
        elif answer == "n":
            capabilities[tool_name] = False

    config.capabilities = capabilities
    save_config(config, config_path)
    print("\nConfiguration saved.")


if __name__ == "__main__":
    main()
