"""Interactive setup wizard for BreadMind first-time configuration."""

from __future__ import annotations

import os
from pathlib import Path

from breadmind.cli.ui import get_ui


async def run_setup(args) -> None:
    """Interactive setup wizard."""
    ui = get_ui()
    ui.panel("BreadMind Setup Wizard", "Interactive first-time configuration")

    # Step 1: Config directory
    config_dir = _ensure_config_dir()

    # Step 2: LLM Provider selection
    provider_name, api_key, model = await _setup_provider()

    # Step 3: API Key verification
    await _verify_api_key(provider_name, api_key, model)

    # Step 4: PostgreSQL connection (optional)
    db_dsn = await _setup_database()

    # Step 5: Write config files
    _write_config(config_dir, provider_name, model, db_dsn)
    _write_env(config_dir, provider_name, api_key, db_dsn)

    # Step 6: Test chat
    await _test_chat(provider_name, api_key, model)

    ui.panel("Setup Complete", f"Config: {config_dir}\nRun: breadmind web")


def _ensure_config_dir() -> str:
    """Ensure config directory exists and return its path."""
    from breadmind.config import get_default_config_dir

    ui = get_ui()
    config_dir = get_default_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    ui.info(f"Config directory: {config_dir}")
    return config_dir


async def _setup_provider() -> tuple[str, str, str]:
    """Select LLM provider, enter API key, and choose model."""
    from breadmind.llm.factory import get_provider_options

    ui = get_ui()
    options = get_provider_options()

    ui.info("Select LLM Provider:")
    rows = []
    for i, opt in enumerate(options, 1):
        free = " (free)" if opt.get("free_tier") else ""
        rows.append([str(i), f"{opt['name']}{free}"])
    ui.table(["#", "Provider"], rows)

    while True:
        choice = ui.prompt(f"Choice (1-{len(options)})")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                break
        except ValueError:
            pass
        ui.error("Invalid choice.")

    selected = options[idx]
    provider_name = selected["id"]

    # API Key input
    api_key = ""
    if selected.get("env_key"):
        # Check if key already exists in environment
        existing = os.environ.get(selected["env_key"], "")
        if existing:
            masked = existing[:8] + "..." + existing[-4:]
            ui.info(f"Found existing key: {masked}")
            if ui.confirm("Use existing key?"):
                api_key = existing

        if not api_key:
            if selected.get("signup_url"):
                ui.info(f"Get API key: {selected['signup_url']}")
            api_key = ui.prompt(f"Enter {selected['env_key']}")

    # Model selection
    models = selected.get("models", [])
    model = models[0] if models else ""
    if len(models) > 1:
        ui.info("Available models:")
        model_rows = [[str(i), m] for i, m in enumerate(models, 1)]
        ui.table(["#", "Model"], model_rows)
        choice = ui.prompt(f"Choice (1-{len(models)})", default="1")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model = models[idx]
        except (ValueError, IndexError):
            pass

    return provider_name, api_key, model


async def _verify_api_key(provider_name: str, api_key: str, model: str) -> None:
    """Verify API key with a health check."""
    ui = get_ui()
    with ui.spinner(f"Verifying {provider_name} API key"):
        try:
            from breadmind.llm.factory import _PROVIDER_REGISTRY

            info = _PROVIDER_REGISTRY.get(provider_name)
            if info and api_key:
                provider = info.cls(api_key=api_key, default_model=model)
                ok = await provider.health_check()
                if ok:
                    ui.success(f"{provider_name} API key verified")
                else:
                    ui.warning(f"{provider_name} key may be invalid")
            else:
                ui.info("Verification skipped")
        except Exception as e:
            ui.error(f"Verification failed: {e}")


async def _setup_database() -> str | None:
    """Configure PostgreSQL connection (optional)."""
    ui = get_ui()
    ui.info("PostgreSQL Setup (optional, enables memory persistence)")
    if not ui.confirm("Configure PostgreSQL?"):
        ui.info("Skipped -- using file-based storage.")
        return None

    dsn = ui.prompt("DSN (e.g., postgresql://user:pass@localhost:5432/breadmind)")
    if not dsn:
        ui.info("Skipped.")
        return None

    # Test connection
    with ui.spinner("Testing database connection"):
        try:
            import asyncpg  # noqa: F811

            conn = await asyncpg.connect(dsn)
            await conn.execute("SELECT 1")
            await conn.close()
            ui.success("Database connection OK")
            return dsn
        except ImportError:
            ui.error("asyncpg not installed: pip install asyncpg")
            return None
        except Exception as e:
            ui.error(f"Connection failed: {e}")
            return None


def _write_config(
    config_dir: str,
    provider: str,
    model: str,
    db_dsn: str | None,
) -> None:
    """Generate config.yaml."""
    config_path = os.path.join(config_dir, "config.yaml")
    ui = get_ui()
    if os.path.exists(config_path):
        if not ui.confirm(f"{config_path} exists. Overwrite?"):
            return

    db_section = ""
    if db_dsn:
        db_section = (
            "\ndatabase:\n"
            '  dsn: "${DATABASE_URL}"\n'
        )

    content = (
        "# BreadMind Configuration\n"
        "llm:\n"
        f"  default_provider: {provider}\n"
        f"  default_model: {model}\n"
        "\n"
        "web:\n"
        '  host: "0.0.0.0"\n'
        "  port: 8080\n"
        f"{db_section}"
    )

    Path(config_path).write_text(content, encoding="utf-8")
    ui.success(f"Written: {config_path}")


def _write_env(
    config_dir: str,
    provider: str,
    api_key: str,
    db_dsn: str | None,
) -> None:
    """Generate .env file with API key and optional DB DSN."""
    env_path = os.path.join(config_dir, ".env")
    lines: list[str] = []

    from breadmind.llm.factory import _PROVIDER_REGISTRY

    info = _PROVIDER_REGISTRY.get(provider)
    if info and info.env_key and api_key:
        lines.append(f"{info.env_key}={api_key}")
    if db_dsn:
        lines.append(f"DATABASE_URL={db_dsn}")

    if lines:
        ui = get_ui()
        Path(env_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        ui.success(f"Written: {env_path}")


async def _test_chat(provider_name: str, api_key: str, model: str) -> None:
    """Run a quick test chat to verify everything works end-to-end."""
    ui = get_ui()
    ui.info("Running test chat...")
    try:
        from breadmind.llm.factory import _PROVIDER_REGISTRY
        from breadmind.llm.base import LLMMessage

        info = _PROVIDER_REGISTRY.get(provider_name)
        if not info or not api_key:
            ui.info("Skipped (no provider/key)")
            return

        with ui.spinner("Sending test message"):
            provider = info.cls(api_key=api_key, default_model=model)
            response = await provider.chat(
                [LLMMessage(role="user", content="Say 'Hello from BreadMind!' in one line.")]
            )
        ui.success(f"Response: {response.content}")
        ui.info(f"Tokens: {response.usage.total_tokens}")
        await provider.close()
    except Exception as e:
        ui.error(f"Test failed: {e}")
