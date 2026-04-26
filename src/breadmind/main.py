import argparse
import asyncio
import logging
import os
import signal
import sys

logger = logging.getLogger(__name__)
from breadmind.config import load_config, load_safety_config, get_default_config_dir, set_env_file_path, load_env_file  # noqa: E402
from breadmind.llm.factory import create_provider  # noqa: E402
from breadmind.monitoring.engine import MonitoringEngine  # noqa: E402


def _find_free_port(preferred: int, max_attempts: int = 10) -> int:
    """Return preferred port if available, otherwise find the next free one."""
    import socket
    for offset in range(max_attempts):
        port = preferred + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return preferred  # fallback, let uvicorn report the error


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser.

    Extracted from ``_parse_args`` so ``main_with_args`` (used by tests)
    can inject a custom argv without re-declaring every subparser.
    """
    parser = argparse.ArgumentParser(description="BreadMind AI Infrastructure Agent")
    sub = parser.add_subparsers(dest="command")

    # breadmind web --host 0.0.0.0 --port 8080
    web_parser = sub.add_parser("web", help="Start web UI mode with uvicorn")
    web_parser.add_argument("--host", default=None, help="Web server host (default: from config or 0.0.0.0)")
    web_parser.add_argument("--port", type=int, default=None, help="Web server port (default: from config or 8080)")
    web_parser.add_argument("--config-dir", default=None, help="Config directory path")
    web_parser.add_argument("--log-level", default=None,
                            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    web_parser.add_argument("--mode", choices=["standalone", "commander", "worker"], default="standalone",
                            help="Run mode: standalone (default), commander, or worker")
    web_parser.add_argument("--commander-url", default="", help="Commander WebSocket URL (worker mode only)")

    # breadmind update
    update_parser = sub.add_parser("update", help="Check for updates and install if available")
    update_parser.add_argument("--check", action="store_true",
                               help="Only check; do not install")
    update_parser.add_argument("--no-restart", action="store_true",
                               help="Do not restart the BreadMind service after updating")

    # breadmind service <action>
    service_parser = sub.add_parser(
        "service",
        help="Manage the BreadMind Windows service (status/install/start/stop/restart/remove)",
    )
    service_sub = service_parser.add_subparsers(dest="service_action")
    service_sub.add_parser("status", help="Show service state (no admin required)")
    svc_install = service_sub.add_parser("install", help="Register service via NSSM (admin required)")
    svc_install.add_argument("--config-dir", default=None, help="Config directory to pass to the service")
    service_sub.add_parser("start",   help="Start service (admin required)")
    service_sub.add_parser("stop",    help="Stop service (admin required)")
    service_sub.add_parser("restart", help="Restart service (admin required)")
    service_sub.add_parser("remove",  help="Unregister service (admin required)")

    # breadmind version
    sub.add_parser("version", help="Show current version")

    # breadmind doctor [--fix] [--yes] [--deep]
    doctor_parser = sub.add_parser("doctor", help="Check system health and configuration")
    doctor_parser.add_argument("--fix", action="store_true",
                               help="Apply auto-fix for detected issues")
    doctor_parser.add_argument("--yes", action="store_true",
                               help="Auto-accept sensitive fixes (use with --fix)")
    doctor_parser.add_argument("--deep", action="store_true",
                               help="Run deeper checks (DB connection, etc.), slower")
    doctor_parser.add_argument("--elevated", action="store_true",
                               help="Auto-invoke admin/elevation commands (will trigger UAC)")

    # breadmind chat
    chat_parser = sub.add_parser("chat", help="Start interactive CLI chat")
    chat_parser.add_argument("--model", default=None, help="Model override (e.g., claude-sonnet-4-6)")
    chat_parser.add_argument("--stream", action="store_true", default=True, help="Enable streaming (default)")
    chat_parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    chat_parser.add_argument("--continue", dest="continue_session", default=None,
                             help="Continue a previous session by ID")
    chat_parser.add_argument("-c", dest="continue_last", action="store_true", default=False,
                             help="Resume the most recent session")
    chat_parser.add_argument("-r", "--resume", dest="resume_session", nargs="?", const="", default=None,
                             help="Resume a session (by ID, or pick from list)")
    chat_parser.add_argument("--config-dir", default=None, help="Config directory path")
    chat_parser.add_argument("--log-level", default=None,
                             choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    # breadmind daemon <start|stop|status>
    daemon_parser = sub.add_parser("daemon", help="Run as background daemon")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_action")

    start_p = daemon_sub.add_parser("start", help="Start daemon")
    start_p.add_argument("--host", default="0.0.0.0")
    start_p.add_argument("--port", type=int, default=8080)
    start_p.add_argument("--config-dir", default=None)

    daemon_sub.add_parser("stop", help="Stop daemon")
    daemon_sub.add_parser("status", help="Check daemon status")

    # breadmind migrate <action>
    migrate_parser = sub.add_parser("migrate", help="Database migration management")
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_action")
    migrate_sub.add_parser("upgrade", help="Run migrations (default: to head)")
    migrate_down = migrate_sub.add_parser("downgrade", help="Downgrade to a specific revision")
    migrate_down.add_argument("revision", help="Target revision")
    migrate_sub.add_parser("history", help="Show migration history")
    migrate_sub.add_parser("check", help="Check if database is up to date")
    migrate_gen = migrate_sub.add_parser("generate", help="Generate a new migration")
    migrate_gen.add_argument("message", help="Migration description")
    migrate_stamp = migrate_sub.add_parser("stamp", help="Stamp DB without running migrations")
    migrate_stamp.add_argument("revision", nargs="?", default="head", help="Revision to stamp (default: head)")

    # breadmind smoke
    smoke_parser = sub.add_parser(
        "smoke",
        help="Go-live preflight smoke gate (targets/credentials/APIs)",
    )
    smoke_parser.add_argument(
        "--targets",
        default="deploy/smoke/pilot-targets.yaml",
        help="Path to pilot-targets.yaml (default: deploy/smoke/pilot-targets.yaml)",
    )
    smoke_parser.add_argument(
        "--timeout", type=float, default=5.0,
        help="Per-check timeout in seconds (default: 5.0)",
    )
    smoke_parser.add_argument(
        "--skip", default="",
        help="Comma-separated check names to skip",
    )
    smoke_parser.add_argument(
        "--verbose", action="store_true",
        help="Print full error details on stderr",
    )
    smoke_parser.add_argument(
        "--config-dir", default=None, help="Config directory path",
    )

    # breadmind setup
    sub.add_parser("setup", help="Interactive setup wizard")

    # breadmind plugin <action>
    plugin_parser = sub.add_parser("plugin", help="Plugin management")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_action")
    plugin_sub.add_parser("list", help="List installed plugins")
    install_p = plugin_sub.add_parser("install", help="Install a plugin")
    install_p.add_argument("source", help="Plugin source (path, git URL, or marketplace name)")
    uninstall_p = plugin_sub.add_parser("uninstall", help="Uninstall a plugin")
    uninstall_p.add_argument("name", help="Plugin name")
    search_p = plugin_sub.add_parser("search", help="Search marketplace")
    search_p.add_argument("query", help="Search query")
    enable_p = plugin_sub.add_parser("enable", help="Enable plugin")
    enable_p.add_argument("name")
    disable_p = plugin_sub.add_parser("disable", help="Disable plugin")
    disable_p.add_argument("name")

    # breadmind backup <action>
    backup_parser = sub.add_parser("backup", help="Database backup management")
    backup_sub = backup_parser.add_subparsers(dest="backup_action")
    backup_create = backup_sub.add_parser("create", help="Create a new backup")
    backup_create.add_argument("--label", default=None, help="Optional label for the backup")
    backup_create.add_argument("--config-dir", default=None, help="Config directory path")
    backup_sub.add_parser("list", help="List available backups")
    backup_restore = backup_sub.add_parser("restore", help="Restore from a backup")
    backup_restore.add_argument("filename", help="Backup filename to restore")
    backup_delete = backup_sub.add_parser("delete", help="Delete a backup")
    backup_delete.add_argument("filename", help="Backup filename to delete")
    backup_sub.add_parser("cleanup", help="Remove old backups exceeding retention limit")

    # breadmind jobs <list|show|watch|cancel|logs>
    jobs_parser = sub.add_parser("jobs", help="Manage long-running coding jobs")
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_action", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--as-user", dest="as_user", default=None)
        p.add_argument("--api-key", dest="api_key", default=None)

    j_list = jobs_sub.add_parser("list", help="List coding jobs")
    _add_common(j_list)
    j_list.add_argument("--status", default=None)
    j_list.add_argument("--mine", dest="mine", action="store_true")
    j_list.add_argument("--all", dest="all_jobs", action="store_true")
    j_list.add_argument("--limit", type=int, default=50)
    j_list.add_argument("--format", dest="fmt", choices=["table", "json"], default="table")

    j_show = jobs_sub.add_parser("show", help="Show job detail")
    _add_common(j_show)
    j_show.add_argument("id")
    j_show.add_argument("--format", dest="fmt", choices=["table", "json"], default="table")

    j_watch = jobs_sub.add_parser("watch", help="Watch job in real time")
    _add_common(j_watch)
    j_watch.add_argument("id")
    j_watch.add_argument("--phase", type=int, default=None)
    j_watch.add_argument("--plain", action="store_true")

    j_cancel = jobs_sub.add_parser("cancel", help="Cancel a running job")
    _add_common(j_cancel)
    j_cancel.add_argument("id")

    j_logs = jobs_sub.add_parser("logs", help="Tail job logs")
    _add_common(j_logs)
    j_logs.add_argument("id")
    j_logs.add_argument("--phase", type=int, required=True)
    j_logs.add_argument("--follow", action="store_true")
    j_logs.add_argument("--lines", type=int, default=200)
    j_logs.add_argument("--plain", action="store_true")

    # breadmind kb backfill <slack|resume|list|cancel> ...
    # The actual subcommand parsing is delegated to
    # ``breadmind.kb.backfill.cli.build_parser`` so the kb-backfill module
    # owns its own argument schema. We capture the rest of argv with
    # REMAINDER and pass it through during dispatch.
    kb_parser = sub.add_parser("kb", help="Knowledge base operations")
    kb_sub = kb_parser.add_subparsers(dest="kb_command")
    bf_parser = kb_sub.add_parser(
        "backfill",
        help="Bulk history backfill (run `... backfill <subcommand> --help` for options)")
    bf_parser.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def _apply_default_command(args: argparse.Namespace) -> argparse.Namespace:
    """If no subcommand was given, default to the ``web`` subcommand."""
    if args.command is None:
        args.command = "web"
        args.host = None
        args.port = None
        args.config_dir = None
        args.log_level = None
        args.mode = "standalone"
        args.commander_url = ""
    return args


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return _apply_default_command(args)


def _dispatch_jobs(args: argparse.Namespace) -> int:
    """Sync dispatch for ``breadmind jobs`` subcommands.

    Jobs CLI talks to a running BreadMind server via HTTP/WebSocket, so it
    does not need the full async bootstrap that ``run()`` performs. We keep
    it as a plain sync function returning an int exit code so ``main_with_args``
    (used by tests) can call it without entering a full asyncio runtime.
    """
    import asyncio
    from breadmind.cli import jobs as cli_jobs
    from breadmind.cli.jobs_watch import cmd_watch

    client = cli_jobs.build_client_from_env(args)
    action = args.jobs_action
    try:
        if action == "list":
            mine = bool(args.mine) or not bool(args.all_jobs)
            return asyncio.run(cli_jobs.cmd_list(
                client, mine=mine, status=args.status,
                limit=args.limit, fmt=args.fmt))
        if action == "show":
            return asyncio.run(cli_jobs.cmd_show(client, args.id, fmt=args.fmt))
        if action == "cancel":
            return asyncio.run(cli_jobs.cmd_cancel(client, args.id))
        if action == "logs":
            return asyncio.run(cli_jobs.cmd_logs(
                client, args.id, phase=args.phase, follow=args.follow,
                lines=args.lines, plain=args.plain))
        if action == "watch":
            token = os.environ.get("BREADMIND_API_KEY", "")
            base = os.environ.get("BREADMIND_URL", "http://localhost:8080")
            return asyncio.run(cmd_watch(
                args.id, plain=args.plain, phase=args.phase,
                base_url=base, api_key=token, token=token))
        return 2
    finally:
        # ``client`` may be ``None`` when tests monkeypatch
        # ``build_client_from_env`` — guard the close call accordingly.
        if client is not None:
            try:
                asyncio.run(client.close())
            except Exception:
                pass


def main_with_args(argv: list[str]) -> int:
    """Entry point that accepts an explicit argv list.

    Used by tests to drive the CLI without touching ``sys.argv``. Jobs
    subcommands are dispatched synchronously here; other commands fall
    through to the async ``run()`` pipeline.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    args = _apply_default_command(args)

    if args.command == "jobs":
        return _dispatch_jobs(args)

    asyncio.run(run(args))
    return 0


async def run_worker(config, args):
    """Bootstrap worker mode — lightweight runtime."""
    from breadmind.network.worker import Worker
    from breadmind.tools.registry import ToolRegistry
    from breadmind.tools.builtin import register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)

    # Register browser tools (optional — requires pip install 'breadmind[browser]')
    try:
        from breadmind.tools.browser import register_browser_tools
        register_browser_tools(registry)
    except Exception:
        pass

    worker = Worker(
        agent_id=getattr(args, "agent_id", "worker"),
        commander_url=getattr(args, "commander_url", "") or config.network.commander_url,
        session_key=b"session-key",  # Derived from mTLS in production
        tool_registry=registry,
    )

    logger.info("Worker mode started, connecting to %s", worker._commander_url)
    # TODO: Connect WebSocket, start heartbeat loop, wait for shutdown


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("breadmind")
    except Exception:
        return "0.0.0"


async def _run_plugin_command(args):
    """Handle `breadmind plugin` subcommands."""
    import os as _os
    from pathlib import Path as _Path

    if _os.name == 'nt':
        plugins_base = _Path(_os.environ.get("APPDATA", _Path.home())) / "breadmind" / "plugins" / "installed"
    else:
        plugins_base = _Path.home() / ".breadmind" / "plugins" / "installed"

    action = getattr(args, "plugin_action", None)

    if action == "list":
        from breadmind.plugins.manager import PluginManager
        mgr = PluginManager(plugins_dir=plugins_base)
        manifests = await mgr.discover()
        if not manifests:
            print("No plugins installed.")
            return
        for m in manifests:
            info = await mgr._registry.get(m.name)
            enabled = info.get("enabled", True) if info else True
            status = "enabled" if enabled else "disabled"
            print(f"  {m.name} v{m.version} [{status}] — {m.description}")

    elif action == "install":
        from breadmind.plugins.manager import PluginManager
        mgr = PluginManager(plugins_dir=plugins_base)
        source = args.source
        # Try marketplace first if it looks like a simple name (no path/URL)
        if not source.startswith(("/", ".", "https://", "git@")) and not _Path(source).exists():
            from breadmind.plugins.marketplace import MarketplaceClient
            marketplace = MarketplaceClient()
            print(f"  Searching marketplace for '{source}'...")
            try:
                target = await marketplace.install(source, plugins_base)
                manifest = await mgr.load_from_directory(target)
                if manifest:
                    print(f"  Installed '{manifest.manifest.name}' from marketplace.")
                return
            except Exception as e:
                print(f"  Marketplace install failed ({e}), trying direct source...")
        manifest = await mgr.install(source)
        print(f"  Installed plugin: {manifest.name} v{manifest.version}")

    elif action == "uninstall":
        from breadmind.plugins.manager import PluginManager
        mgr = PluginManager(plugins_dir=plugins_base)
        await mgr.uninstall(args.name)
        print(f"  Uninstalled plugin: {args.name}")

    elif action == "search":
        from breadmind.plugins.marketplace import MarketplaceClient
        marketplace = MarketplaceClient()
        results = await marketplace.search(args.query)
        if not results:
            print("  No plugins found.")
            return
        for p in results:
            print(f"  {p.get('name', '?')} v{p.get('version', '?')} — {p.get('description', '')}")

    elif action == "enable":
        from breadmind.plugins.manager import PluginManager
        mgr = PluginManager(plugins_dir=plugins_base)
        await mgr._registry.set_enabled(args.name, True)
        print(f"  Enabled plugin: {args.name}")

    elif action == "disable":
        from breadmind.plugins.manager import PluginManager
        mgr = PluginManager(plugins_dir=plugins_base)
        await mgr._registry.set_enabled(args.name, False)
        print(f"  Disabled plugin: {args.name}")

    else:
        print("Usage: breadmind plugin <list|install|uninstall|search|enable|disable>")


async def _run_backup_command(args):
    """Handle `breadmind backup` subcommands."""
    from breadmind.storage.backup import BackupManager, BackupConfig, BackupError

    action = getattr(args, "backup_action", None)
    if not action:
        print("Usage: breadmind backup <create|list|restore|delete|cleanup>")
        return

    config_dir = getattr(args, "config_dir", None) or get_default_config_dir()
    config = load_config(config_dir) if os.path.isdir(config_dir) else load_config("config")

    db_config = {
        "host": config.database.host,
        "port": config.database.port,
        "name": config.database.name,
        "user": config.database.user,
        "password": config.database.password,
    }
    mgr = BackupManager(db_config, BackupConfig())

    try:
        if action == "create":
            label = getattr(args, "label", None)
            print("  Creating backup...")
            info = await mgr.create_backup(label=label)
            print(f"  Backup created: {info.filename} ({info.size_bytes:,} bytes)")

        elif action == "list":
            backups = mgr.list_backups()
            if not backups:
                print("  No backups found.")
                return
            for b in backups:
                ts = b.created_at.strftime("%Y-%m-%d %H:%M:%S")
                size_mb = b.size_bytes / (1024 * 1024)
                gz = " (compressed)" if b.compressed else ""
                print(f"  {b.filename}  {size_mb:.1f} MB  {ts}{gz}")

        elif action == "restore":
            filename = args.filename
            from pathlib import Path
            backup_path = Path(mgr._backup_dir) / filename
            if not backup_path.exists():
                print(f"  Error: Backup file not found: {filename}")
                return
            confirm = input(f"  Restore '{filename}'? This may overwrite existing data. [y/N]: ")
            if confirm.strip().lower() != "y":
                print("  Restore cancelled.")
                return
            print("  Restoring...")
            await mgr.restore_backup(str(backup_path))
            print("  Database restored successfully.")

        elif action == "delete":
            filename = args.filename
            if mgr.delete_backup(filename):
                print(f"  Deleted: {filename}")
            else:
                print(f"  Backup not found: {filename}")

        elif action == "cleanup":
            count = mgr.cleanup_old()
            print(f"  Cleaned up {count} old backup(s).")

        else:
            print("Usage: breadmind backup <create|list|restore|delete|cleanup>")

    except BackupError as exc:
        print(f"  Error: {exc}")


async def run(args: argparse.Namespace | None = None):
    if args is None:
        args = _parse_args()

    if args.command == "version":
        print(f"BreadMind v{_get_version()}")
        return

    if args.command == "update":
        from breadmind.cli.updater import run_update
        rc = await run_update(
            check_only=getattr(args, "check", False),
            no_restart=getattr(args, "no_restart", False),
        )
        sys.exit(rc)

    if args.command == "service":
        from breadmind.cli.service import run_service_command
        rc = await run_service_command(args)
        sys.exit(rc)

    if args.command == "doctor":
        from breadmind.cli.doctor import run_doctor
        await run_doctor(args)
        return

    if args.command == "migrate":
        from breadmind.storage.migrator import run_migration_command
        action = getattr(args, "migrate_action", None)
        if not action:
            print("Usage: breadmind migrate <upgrade|downgrade|history|check|generate|stamp>")
            return
        extra_args: list[str] = []
        if action == "downgrade":
            extra_args = [args.revision]
        elif action == "generate":
            extra_args = [args.message]
        elif action == "stamp":
            extra_args = [getattr(args, "revision", "head")]
        run_migration_command(action, extra_args)
        return

    if args.command == "smoke":
        from pathlib import Path as _SmokePath
        from breadmind.smoke.runner import SmokeRunner, render_table, ExitCode
        from breadmind.smoke.checks import build_checks, CheckOutcome, CheckStatus
        from breadmind.smoke.targets import load_targets, TargetsError
        from breadmind.smoke._redact import redact_secrets
        from breadmind.storage.credential_vault import CredentialVault

        targets_path = _SmokePath(args.targets)
        # Config-first: if targets file is missing/malformed we report a
        # single ConfigCheck FAIL and exit 2 WITHOUT touching DB or vault.
        try:
            targets = load_targets(targets_path)
        except TargetsError as exc:
            outcome = CheckOutcome(
                name="config", status=CheckStatus.FAIL,
                detail=redact_secrets(str(exc)),
            )
            print(render_table([outcome]))
            sys.exit(int(ExitCode.CONFIG_ERROR))

        # Bootstrap DB using the same pattern as init_database() — connect
        # directly so we can fetch vault credentials without dragging in
        # the full agent bootstrap.
        config_dir_smoke = args.config_dir or get_default_config_dir()
        if os.path.isdir(config_dir_smoke) and os.path.exists(os.path.join(config_dir_smoke, "config.yaml")):
            smoke_config = load_config(config_dir_smoke)
        elif os.path.isdir("config"):
            smoke_config = load_config("config")
            config_dir_smoke = "config"
        else:
            smoke_config = load_config(config_dir_smoke)

        # Load .env so DATABASE_URL, CONFLUENCE_EMAIL, AZURE_OPENAI_ENDPOINT, etc.
        # are available to downstream checks.
        env_file_smoke = os.path.join(config_dir_smoke, ".env")
        set_env_file_path(env_file_smoke)
        load_env_file(env_file_smoke)

        from breadmind.storage.database import Database as _SmokeDatabase
        _db_cfg = smoke_config.database
        _dsn = f"postgresql://{_db_cfg.user}:{_db_cfg.password}@{_db_cfg.host}:{_db_cfg.port}/{_db_cfg.name}"
        db = _SmokeDatabase(_dsn)
        try:
            await db.connect()
        except Exception as e:
            logger.warning("smoke: database connect failed (%s); vault lookups will return None", e)

        vault = CredentialVault(db)
        confluence_email = os.environ.get("CONFLUENCE_EMAIL", "")

        checks = build_checks(
            targets_path=targets_path,
            vault=vault,
            confluence_email=confluence_email,
        )

        # Inject resolved secrets into auth-capable checks.
        from breadmind.smoke.checks.slack_auth import SlackAuthCheck
        from breadmind.smoke.checks.slack_channels import SlackChannelsCheck
        from breadmind.smoke.checks.slack_events import SlackEventsCheck
        from breadmind.smoke.checks.confluence_auth import ConfluenceAuthCheck
        from breadmind.smoke.checks.confluence_spaces import ConfluenceSpacesCheck

        async def _safe_retrieve(key: str) -> str:
            try:
                return (await vault.retrieve(key)) or ""
            except Exception:
                return ""

        bot_token = await _safe_retrieve("slack_bot_token")
        app_token = await _safe_retrieve("slack_app_token")
        conf_token = await _safe_retrieve("confluence_token")

        slack_auth = next(c for c in checks if isinstance(c, SlackAuthCheck))
        slack_auth.token = bot_token
        # slack_channels consumes bot_user_id populated by slack_auth during run
        slack_channels = next(c for c in checks if isinstance(c, SlackChannelsCheck))
        slack_channels.token = bot_token
        original_run = slack_channels.run

        async def _patched_channels_run(targets, timeout):
            slack_channels.bot_user_id = slack_auth.bot_user_id
            return await original_run(targets, timeout)

        slack_channels.run = _patched_channels_run  # type: ignore[assignment]

        slack_events = next(c for c in checks if isinstance(c, SlackEventsCheck))
        slack_events.app_token = app_token

        for c in checks:
            if isinstance(c, (ConfluenceAuthCheck, ConfluenceSpacesCheck)):
                c.api_token = conf_token

        skip = {s for s in (args.skip or "").split(",") if s}
        runner = SmokeRunner(
            checks=checks, targets=targets,
            timeout=args.timeout, skip=skip,
        )
        exit_code, outcomes = await runner.run()
        print(render_table(outcomes))
        try:
            await db.disconnect()
        except Exception:
            pass
        sys.exit(int(exit_code))

    if args.command == "plugin":
        await _run_plugin_command(args)
        return

    if args.command == "backup":
        await _run_backup_command(args)
        return

    if args.command == "chat":
        from breadmind.cli.chat import run_chat
        await run_chat(args)
        return

    if args.command == "daemon":
        from breadmind.cli.daemon import run_daemon, stop_daemon, daemon_status
        action = getattr(args, "daemon_action", "start")
        if action == "stop":
            await stop_daemon(args)
        elif action == "status":
            await daemon_status(args)
        else:
            await run_daemon(args)
        return

    if args.command == "setup":
        from breadmind.cli.setup import run_setup
        await run_setup(args)
        return

    if args.command == "kb":
        kb_command = getattr(args, "kb_command", None)
        if kb_command == "backfill":
            # T19 (review fix): delegate to ``cli.main_async`` so subcommands
            # (slack/resume/list/cancel) actually run instead of just echoing
            # the parsed namespace. We bootstrap a lightweight stack
            # (config + .env + DB + CredentialVault) — same pattern as the
            # ``smoke`` branch — without dragging in the agent/tools graph
            # the web/chat paths need.
            from breadmind.kb.backfill.cli import main_async as bf_main_async
            from breadmind.kb.redactor import Redactor
            from breadmind.memory.embedding import EmbeddingService
            from breadmind.storage.credential_vault import CredentialVault
            from breadmind.storage.database import Database as _KbDatabase

            # Resolve config dir using the same fall-through used by smoke /
            # the main bootstrap so users don't get surprised by .env/config
            # mismatches between commands.
            kb_config_dir = getattr(args, "config_dir", None) or get_default_config_dir()
            if os.path.isdir(kb_config_dir) and os.path.exists(
                os.path.join(kb_config_dir, "config.yaml")
            ):
                kb_config = load_config(kb_config_dir)
            elif os.path.isdir("config"):
                kb_config = load_config("config")
                kb_config_dir = "config"
            else:
                kb_config = load_config(kb_config_dir)
            kb_env_file = os.path.join(kb_config_dir, ".env")
            set_env_file_path(kb_env_file)
            load_env_file(kb_env_file)

            kb_db_cfg = kb_config.database
            kb_dsn = (
                f"postgresql://{kb_db_cfg.user}:{kb_db_cfg.password}"
                f"@{kb_db_cfg.host}:{kb_db_cfg.port}/{kb_db_cfg.name}"
            )
            kb_db = _KbDatabase(kb_dsn)
            try:
                await kb_db.connect()
            except Exception as exc:
                print(f"  kb backfill: database connect failed ({exc})")
                sys.exit(2)

            kb_vault = CredentialVault(kb_db)
            kb_redactor = Redactor.default()
            kb_embedder = EmbeddingService(provider="fastembed")
            # TODO(kb-backfill-followup): no production-grade Slack web-API
            # session class exists yet — the SlackBackfillAdapter expects
            # ``session.call(method, **kwargs)`` (slack-sdk-shaped). Until a
            # real session is wired, slack/resume runs will fail at
            # ``auth.test`` with a clear AttributeError. ``list`` and
            # ``cancel`` work today (they only touch DB).
            kb_slack_session = None
            try:
                rc = await bf_main_async(
                    args.rest,
                    db=kb_db,
                    redactor=kb_redactor,
                    embedder=kb_embedder,
                    slack_session=kb_slack_session,
                    vault=kb_vault,
                )
            finally:
                try:
                    await kb_db.disconnect()
                except Exception:
                    pass
            sys.exit(rc)
        print("Usage: breadmind kb <backfill> ...")
        return

    config_dir = args.config_dir or get_default_config_dir()

    # Try platform config dir first, fall back to local ./config
    if os.path.isdir(config_dir) and os.path.exists(os.path.join(config_dir, "config.yaml")):
        config = load_config(config_dir)
        safety_cfg = load_safety_config(config_dir)
        print(f"  Config: {config_dir}")
    elif os.path.isdir("config"):
        config = load_config("config")
        safety_cfg = load_safety_config("config")
        config_dir = "config"
        print("  Config: ./config (local)")
    else:
        config = load_config(config_dir)  # will return defaults
        safety_cfg = load_safety_config(config_dir)
        print("  Config: defaults (no config dir found)")

    config.validate()

    # Load and set .env file path based on resolved config dir
    env_file = os.path.join(config_dir, ".env")
    set_env_file_path(env_file)
    load_env_file(env_file)

    # Configure logging
    log_level = args.log_level or config.logging.level
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Determine run mode
    mode = getattr(args, "mode", "standalone") if args else config.network.mode

    if mode == "worker":
        await run_worker(config, args)
        return

    # Initialize all components via bootstrap
    from breadmind.core.bootstrap import init_database, init_tools, init_memory, init_agent, init_messenger

    db = await init_database(config, config_dir)

    # Load persisted settings from DB (including previously dead settings)
    from breadmind.config import apply_db_settings
    db_extra_settings: dict = await apply_db_settings(config, db)

    # apply_db_settings catches and silently ignores errors, which can leave
    # API keys un-hydrated into os.environ if an earlier DB call raised.
    # Run the API key hydration explicitly so create_provider always sees
    # persisted keys on startup.
    from breadmind.config_env import load_api_keys_from_db
    try:
        await load_api_keys_from_db(db)
    except Exception as e:
        logger.warning("explicit load_api_keys_from_db failed: %s", e)

    # First-run setup wizard (CLI mode only, web has its own UI)
    if not args.command == "web":
        from breadmind.core.setup_wizard import is_first_run_async, run_cli_wizard
        if await is_first_run_async(db):
            await run_cli_wizard(db, config)

    # Initialize credential vault BEFORE create_provider so API keys
    # persisted via Settings UI are hydrated into os.environ and the
    # factory picks them up on startup (not just on hot-reload).
    credential_vault = None
    try:
        from breadmind.storage.credential_vault import CredentialVault
        credential_vault = CredentialVault(db)
        await credential_vault.migrate_plaintext_credentials()
        from breadmind.core.router_manager import get_router_manager
        get_router_manager().set_vault(credential_vault)

        try:
            apikey_ids = await credential_vault.list_ids(prefix="apikey:")
        except Exception as hydrate_exc:
            logger.warning("apikey hydration list failed: %s", hydrate_exc)
            apikey_ids = []
        for vault_id in apikey_ids:
            env_key = vault_id.removeprefix("apikey:")
            if not env_key:
                continue
            if os.environ.get(env_key, "").strip():
                continue  # honour explicit env override
            try:
                secret = await credential_vault.retrieve(vault_id)
            except Exception as retrieve_exc:
                logger.warning("apikey retrieve failed for %s: %s", vault_id, retrieve_exc)
                secret = None
            if secret:
                os.environ[env_key] = secret
    except Exception as e:
        logger.warning("Credential vault init failed: %s", e)

    provider = create_provider(config)
    registry, guard, mcp_manager, search_engine, meta_tools = await init_tools(config, safety_cfg)

    # DB safety 설정이 있으면 guard에 적용 (DB 우선, safety.yaml은 기본값)
    if db_extra_settings.get("safety_blacklist"):
        guard.update_blacklist(db_extra_settings["safety_blacklist"])
    if db_extra_settings.get("safety_approval"):
        guard.update_require_approval(db_extra_settings["safety_approval"])
    if db_extra_settings.get("safety_permissions"):
        perms = db_extra_settings["safety_permissions"]
        guard.update_user_permissions(
            perms.get("user_permissions", {}),
            perms.get("admin_users", []),
        )

    memory_components = await init_memory(
        db, provider, config, registry, mcp_manager, search_engine,
        vault=credential_vault,
    )
    agent, behavior_tracker, audit_logger, metrics_collector = await init_agent(
        config, provider, registry, guard, db, memory_components,
    )

    # Initialize central event bus
    from breadmind.core.events import get_event_bus
    event_bus = get_event_bus()

    # Initialize monitoring engine
    monitoring_engine = MonitoringEngine()
    await monitoring_engine.start()

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        shutdown_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: shutdown_event.set())
    else:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    builtin_count = len([t for t in registry.get_all_definitions() if registry.get_tool_source(t.name) == "builtin"])
    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print(f"  Built-in tools: {builtin_count}")
    print(f"  Meta tools: {len(meta_tools)}")
    print(f"  MCP servers: {len(config.mcp.servers)}")

    # Resolve host/port from CLI args or config, auto-find free port if needed
    web_host = args.host or config.web.host
    web_port = args.port or config.web.port
    web_port = _find_free_port(web_port)
    if web_port != (args.port or config.web.port):
        print(f"  Port {args.port or config.web.port} in use, using {web_port}")

    # Background update checker
    async def check_updates_periodically():
        import aiohttp
        while True:
            await asyncio.sleep(config.polling.update_check_interval)
            try:
                current = "0.1.0"
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://pypi.org/pypi/breadmind/json",
                        timeout=aiohttp.ClientTimeout(total=config.timeouts.pypi_check),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            latest = data.get("info", {}).get("version", current)
                            if latest != current:
                                print(f"  Update available: v{current} → v{latest}")
                                # If web app running, broadcast notification
                                if args.command == "web" and 'web_app' in dir():
                                    await web_app.broadcast_event({
                                        "type": "update_available",
                                        "current": current,
                                        "latest": latest,
                                    })
            except Exception:
                pass

    update_task = asyncio.create_task(check_updates_periodically())

    # Auto-discover and install skills from marketplace (background)
    async def _discover_skills():
        try:
            from breadmind.core.bootstrap import discover_and_install_skills
            await discover_and_install_skills(
                skill_store=memory_components["skill_store"],
                search_engine=search_engine,
            )
        except Exception as e:
            logger.debug("Skill auto-discovery skipped: %s", e)

    asyncio.create_task(_discover_skills())

    # Extract commonly used memory components
    working_memory = memory_components["working_memory"]
    performance_tracker = memory_components["performance_tracker"]
    skill_store = memory_components["skill_store"]
    smart_retriever = memory_components["smart_retriever"]
    context_builder = memory_components.get("context_builder")
    profiler = memory_components.get("profiler")
    mcp_store = memory_components.get("mcp_store")

    # Start memory garbage collector
    from breadmind.memory.gc import MemoryGC
    memory_gc = MemoryGC(
        working_memory=working_memory,
        episodic_memory=memory_components.get("episodic_memory"),
        semantic_memory=memory_components.get("semantic_memory"),
        interval_seconds=3600,      # Run every hour
        decay_threshold=0.1,        # Remove notes with <10% relevance
        max_cached_notes=500,       # Cap in-memory episodic cache
        kg_max_age_days=90,         # Prune orphaned KG entities after 90 days
        env_refresh_interval=6,     # Refresh environment every 6 cycles (6h)
        db=db,
    )
    await memory_gc.start()

    try:
        if args.command == "web":
            import uvicorn
            from breadmind.web.app import WebApp

            # Token manager for worker provisioning
            from breadmind.network.token_manager import TokenManager
            token_manager = TokenManager(db=db)
            await token_manager.load_from_db()

            swarm_manager = None

            # Initialize messenger auto-connect system
            from breadmind.messenger.router import MessageRouter
            message_router = MessageRouter()
            messenger_components = None
            try:
                messenger_components = await init_messenger(
                    db, message_router, agent_handle_message=agent.handle_message,
                )
            except Exception as e:
                logger.warning("Messenger init failed: %s", e)

            # Start coding job notifier for messenger alerts
            try:
                from breadmind.coding.job_notifier import JobNotifier
                _job_notifier = JobNotifier(message_router=message_router)
                _job_notifier.start()
            except Exception as e:
                logger.debug("JobNotifier not started: %s", e)

            # Wire orchestrator into builtin tool
            if messenger_components:
                from breadmind.tools.builtin import set_orchestrator
                set_orchestrator(messenger_components["orchestrator"])

            # Initialize background job manager (requires PostgreSQL + Redis)
            bg_job_manager = None
            try:
                if hasattr(db, "acquire"):
                    from breadmind.storage.bg_jobs_store import BgJobsStore
                    from breadmind.tasks.manager import BackgroundJobManager
                    from breadmind.tools.builtin import set_bg_job_manager

                    bg_store = BgJobsStore(db)
                    bg_job_manager = BackgroundJobManager(
                        bg_store,
                        redis_url=config.task.redis_url,
                        max_monitors=config.task.max_concurrent_monitors,
                    )
                    await bg_job_manager.recover_on_startup()
                    await bg_job_manager.cleanup_old_jobs(config.task.completed_retention_days)
                    set_bg_job_manager(bg_job_manager)
                    logger.info("Background job manager initialized")
            except Exception as e:
                logger.warning("Background jobs not available: %s", e)

            # Commander mode initialization
            commander = None
            if mode == "commander":
                from breadmind.network.commander import Commander
                from breadmind.network.registry import AgentRegistry

                agent_registry = AgentRegistry()
                commander = Commander(
                    registry=agent_registry,
                    llm_provider=provider,
                    session_key=config.security.api_keys[0].encode() if config.security.api_keys else b"default-session-key",
                )
                logger.info("Commander mode initialized")

            # Initialize webhook automation system
            from breadmind.web.webhook import WebhookManager
            webhook_manager = WebhookManager()
            webhook_manager.set_message_handler(agent.handle_message)

            webhook_automation_store = None
            webhook_rule_engine = None
            webhook_pipeline_executor = None
            try:
                from breadmind.webhook.store import WebhookAutomationStore
                from breadmind.webhook.rule_engine import RuleEngine
                from breadmind.webhook.pipeline_executor import PipelineExecutor
                from breadmind.webhook.models import ActionType
                from breadmind.webhook.actions import (
                    AgentActionHandler, ToolActionHandler, HttpActionHandler,
                    NotifyActionHandler, TransformActionHandler,
                )

                webhook_automation_store = WebhookAutomationStore(db=db)
                webhook_rule_engine = RuleEngine()

                action_handlers = {
                    ActionType.SEND_TO_AGENT: AgentActionHandler(message_handler=agent.handle_message),
                    ActionType.CALL_TOOL: ToolActionHandler(tool_registry=registry),
                    ActionType.HTTP_REQUEST: HttpActionHandler(),
                    ActionType.NOTIFY: NotifyActionHandler(message_router=message_router),
                    ActionType.TRANSFORM: TransformActionHandler(),
                }
                webhook_pipeline_executor = PipelineExecutor(action_handlers=action_handlers)

                webhook_manager.set_automation(
                    store=webhook_automation_store,
                    rule_engine=webhook_rule_engine,
                    pipeline_executor=webhook_pipeline_executor,
                )

                # Load persisted rules and pipelines from DB
                await webhook_automation_store.load()

                # Load persisted webhook endpoints from DB
                if db:
                    try:
                        endpoints_data = await db.get_setting("webhook_endpoints")
                        if endpoints_data:
                            from breadmind.web.webhook import WebhookEndpoint
                            for ep_data in endpoints_data:
                                ep = WebhookEndpoint(
                                    id=ep_data["id"],
                                    name=ep_data["name"],
                                    path=ep_data["path"],
                                    event_type=ep_data.get("event_type", "generic"),
                                    action=ep_data.get("action", "Webhook: {payload}"),
                                    enabled=ep_data.get("enabled", True),
                                    secret=ep_data.get("secret", ""),
                                    fallback_strategy=ep_data.get("fallback_strategy", "forward_to_agent"),
                                    fallback_pipeline_id=ep_data.get("fallback_pipeline_id", ""),
                                    permission_level=ep_data.get("permission_level", "standard"),
                                )
                                webhook_manager.add_endpoint(ep)
                    except Exception as e:
                        logger.debug("No persisted webhook endpoints: %s", e)

                logger.info("Webhook automation initialized (%d rules, %d pipelines)",
                    len(webhook_automation_store.list_rules()),
                    len(webhook_automation_store.list_pipelines()))
            except Exception as e:
                logger.warning("Webhook automation not available: %s", e)

            # Periodic flush of expansion data
            async def _flush_expansion_data():
                while True:
                    await asyncio.sleep(config.polling.data_flush_interval)
                    try:
                        await performance_tracker.flush_to_db()
                        await skill_store.flush_to_db()
                        if profiler:
                            await profiler.flush_to_db()
                        # Auto-cleanup underperforming auto-created roles
                        if swarm_manager and performance_tracker:
                            for role_info in swarm_manager.get_available_roles():
                                name = role_info["role"]
                                member = swarm_manager._roles.get(name)
                                if not member or getattr(member, 'source', 'manual') != "auto":
                                    continue
                                stats = performance_tracker.get_role_stats(name)
                                if stats and stats.total_runs > 0 and stats.success_rate < 0.2:
                                    swarm_manager.remove_role(name)
                                    logger.info(f"Auto-removed underperforming role '{name}' (success={stats.success_rate:.0%})")
                    except Exception as e:
                        logger.error(f"Expansion data flush error: {e}")

            asyncio.create_task(_flush_expansion_data())

            # Periodic memory promotion (working → episodic → semantic)
            async def _auto_promote_memory():
                while True:
                    await asyncio.sleep(config.polling.auto_cleanup_interval)
                    if context_builder:
                        try:
                            result = await context_builder.auto_promote(message_threshold=8)
                            if result["episodic_notes"] > 0 or result["semantic_entities"] > 0:
                                logger.info(
                                    f"Memory promotion: {result['episodic_notes']} notes, "
                                    f"{result['semantic_entities']} entities"
                                )
                        except Exception as e:
                            logger.error(f"Memory promotion failed: {e}")

            asyncio.create_task(_auto_promote_memory())

            # Initialize plugin manager for web mode
            plugin_mgr = None
            try:
                from breadmind.plugins.manager import PluginManager
                from breadmind.plugins.container import ServiceContainer
                from pathlib import Path as _PluginPath
                import os as _os

                if _os.name == 'nt':
                    _plugins_base = _PluginPath(_os.environ.get("APPDATA", _PluginPath.home())) / "breadmind" / "plugins" / "installed"
                else:
                    _plugins_base = _PluginPath.home() / ".breadmind" / "plugins" / "installed"

                # Build ServiceContainer with all available services
                _container = ServiceContainer()
                _container.register("config", config)
                _container.register("db", db)
                _container.register("llm_provider", provider)
                _container.register("tool_registry", registry)
                _container.register("safety_guard", guard)
                _container.register("mcp_manager", mcp_manager)
                _container.register("search_engine", search_engine)
                _container.register("working_memory", working_memory)
                _container.register("episodic_memory", memory_components.get("episodic_memory"))
                _container.register("semantic_memory", memory_components.get("semantic_memory"))
                _container.register("smart_retriever", smart_retriever)
                _container.register("skill_store", skill_store)
                _container.register("performance_tracker", performance_tracker)
                _container.register("swarm_manager", swarm_manager)
                _container.register("swarm_db", db)
                if profiler:
                    _container.register("profiler", profiler)
                if context_builder:
                    _container.register("context_builder", context_builder)
                if memory_components.get("adapter_registry"):
                    _container.register("adapter_registry", memory_components["adapter_registry"])
                if memory_components.get("oauth_manager"):
                    _container.register("oauth_manager", memory_components["oauth_manager"])
                if credential_vault:
                    _container.register("credential_vault", credential_vault)
                if messenger_components:
                    _container.register("orchestrator", messenger_components["orchestrator"])
                if bg_job_manager:
                    _container.register("bg_job_manager", bg_job_manager)

                plugin_mgr = PluginManager(
                    plugins_dir=_plugins_base,
                    tool_registry=registry,
                    container=_container,
                )

                # Load builtin plugins (sorted by priority)
                _builtin_dir = _PluginPath(__file__).resolve().parent / "plugins" / "builtin"
                builtin_count = await plugin_mgr.load_builtin(_builtin_dir)

                # Load user-installed plugins
                await plugin_mgr.load_all()
                logger.info(f"Plugins loaded: {len(plugin_mgr.loaded_plugins)} ({builtin_count} builtin)")
            except Exception as e:
                logger.warning(f"Plugin system initialization failed: {e}")

            web_app = WebApp(
                message_handler=agent.handle_message,
                tool_registry=registry,
                mcp_manager=mcp_manager,
                config=config,
                monitoring_engine=monitoring_engine,
                safety_config=safety_cfg,
                agent=agent,
                audit_logger=audit_logger,
                metrics_collector=metrics_collector,
                database=db,
                mcp_store=mcp_store,
                safety_guard=guard,
                working_memory=working_memory,
                swarm_manager=swarm_manager,
                skill_store=skill_store,
                performance_tracker=performance_tracker,
                search_engine=search_engine,
                token_manager=token_manager,
                commander=commander,
                message_router=message_router,
                messenger_security=messenger_components["security"] if messenger_components else None,
                lifecycle_manager=messenger_components["lifecycle"] if messenger_components else None,
                orchestrator=messenger_components["orchestrator"] if messenger_components else None,
                bg_job_manager=bg_job_manager,
                embedding_service=memory_components.get("embedding_service"),
                plugin_mgr=plugin_mgr,
                webhook_manager=webhook_manager,
                webhook_automation_store=webhook_automation_store,
                webhook_rule_engine=webhook_rule_engine,
                webhook_pipeline_executor=webhook_pipeline_executor,
            )
            # Expose personal assistant components to web routes
            if memory_components.get("adapter_registry"):
                web_app.app.state.adapter_registry = memory_components["adapter_registry"]
            if memory_components.get("oauth_manager"):
                web_app.app.state.oauth_manager = memory_components["oauth_manager"]
            if credential_vault:
                web_app.app.state.credential_vault = credential_vault

            # Wire EventBus → WebSocket broadcast (all events forwarded to UI)
            async def _event_to_websocket(event):
                await web_app.broadcast_event({
                    "type": event.type.value,
                    "data": event.data,
                    "source": event.source,
                    "timestamp": event.timestamp.isoformat(),
                })
            event_bus.subscribe_all(_event_to_websocket)

            print(f"  Starting web server on {web_host}:{web_port}")
            server_config = uvicorn.Config(
                web_app.app, host=web_host, port=web_port, log_level=log_level.lower(),
            )
            server = uvicorn.Server(server_config)
            await server.serve()
        else:
            print("Type 'quit' to exit.\n")
            while not shutdown_event.is_set():
                try:
                    user_input = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: input("you> ").strip(),
                    )
                except (EOFError, KeyboardInterrupt):
                    break
                if not user_input or user_input.lower() in ("quit", "exit"):
                    break

                response = await agent.handle_message(user_input, user="local", channel="cli")
                print(f"breadmind> {response}\n")
    finally:
        update_task.cancel()
        # Shutdown messenger lifecycle if initialized (only in web mode)
        try:
            if messenger_components:  # noqa: F821
                await messenger_components["lifecycle"].shutdown()
        except (NameError, Exception) as e:
            if not isinstance(e, NameError):
                logger.warning("Messenger lifecycle shutdown error: %s", e)
        await memory_gc.stop()
        await monitoring_engine.stop()
        await mcp_manager.stop_all()
        working_memory._sessions.clear()
        # Close all pooled HTTP sessions
        try:
            from breadmind.core.http_pool import get_session_manager
            await get_session_manager().close_all()
        except Exception as e:
            logger.warning("HTTP session pool shutdown error: %s", e)
        if db:
            await db.disconnect()


def main():
    rc = main_with_args(sys.argv[1:])
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
