from __future__ import annotations

import argparse
import asyncio
import sys


async def cmd_setup(args):
    """Interactive messenger connection wizard."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    orchestrator = components["orchestrator"]

    platforms = ["slack", "discord", "telegram", "whatsapp", "gmail", "signal"]
    platform = args.platform

    if not platform:
        print("\nAvailable messenger platforms:")
        for i, p in enumerate(platforms, 1):
            print(f"  {i}. {p}")
        try:
            choice = input("\nSelect platform number: ").strip()
            idx = int(choice) - 1
            platform = platforms[idx]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return

    print(f"\nStarting {platform} connection...")
    state = await orchestrator.start_connection(platform, "cli")

    while state.status not in ("completed", "failed"):
        print(f"\n-- Step {state.current_step}/{state.total_steps}: {state.step_info.title} --")
        print(state.message)

        if state.step_info and state.step_info.action_url:
            print(f"\nLink: {state.step_info.action_url}")

        if state.step_info and state.step_info.action_type == "user_input":
            user_input = {}
            for field in state.step_info.input_fields or []:
                prompt = f"{field.label}"
                if field.placeholder:
                    prompt += f" ({field.placeholder})"
                prompt += ": "
                if field.secret:
                    import getpass
                    value = getpass.getpass(prompt)
                else:
                    value = input(prompt)
                if value:
                    user_input[field.name] = value
            state = await orchestrator.process_step(state.session_id, user_input)
        elif state.step_info and state.step_info.action_type == "user_action":
            input("\nPress Enter after completing the above action...")
            state = await orchestrator.process_step(state.session_id, {})
        elif state.step_info and state.step_info.action_type == "oauth_redirect":
            print("\nOpen the link above in your browser to authenticate.")
            input("Press Enter after completing authentication...")
            state = await orchestrator.process_step(state.session_id, {})
        else:
            state = await orchestrator.process_step(state.session_id, {})

    if state.status == "completed":
        print(f"\n[OK] {state.message}")
    else:
        print(f"\n[FAIL] {state.message}")
        if state.error:
            print(f"   Error: {state.error}")

    await db.disconnect()


async def cmd_status(args):
    """Check messenger status."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    lifecycle = components["lifecycle"]

    statuses = lifecycle.get_all_statuses()
    print("\nMessenger Status:")
    print(f"{'Platform':<12} {'State':<15} {'Retry':<6} {'Error'}")
    print("-" * 60)
    for platform, status in statuses.items():
        print(
            f"{platform:<12} {status.state.value:<15} "
            f"{status.retry_count:<6} {status.last_error or '-'}"
        )

    await lifecycle.shutdown()
    await db.disconnect()


async def cmd_restart(args):
    """Restart messenger gateway."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    lifecycle = components["lifecycle"]

    if args.platform:
        success = await lifecycle.restart_gateway(args.platform)
        print(f"{args.platform}: {'restarted' if success else 'restart failed'}")
    else:
        results = await lifecycle.auto_start_all()
        for platform, ok in results.items():
            print(f"{platform}: {'started' if ok else 'not started'}")

    await lifecycle.shutdown()
    await db.disconnect()


def add_messenger_subparser(subparsers):
    """Register messenger subcommands into the main CLI parser."""
    msg_parser = subparsers.add_parser("messenger", help="Messenger management")
    msg_sub = msg_parser.add_subparsers(dest="messenger_cmd")

    setup_p = msg_sub.add_parser("setup", help="Connect a messenger platform")
    setup_p.add_argument("--platform", choices=[
        "slack", "discord", "telegram", "whatsapp", "gmail", "signal"
    ])
    setup_p.set_defaults(func=lambda args: asyncio.run(cmd_setup(args)))

    status_p = msg_sub.add_parser("status", help="Check messenger status")
    status_p.set_defaults(func=lambda args: asyncio.run(cmd_status(args)))

    restart_p = msg_sub.add_parser("restart", help="Restart messenger gateway")
    restart_p.add_argument("platform", nargs="?", help="Platform to restart")
    restart_p.set_defaults(func=lambda args: asyncio.run(cmd_restart(args)))
