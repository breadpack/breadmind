"""Interactive setup wizard for BreadMind first-time configuration."""

from __future__ import annotations

import os
from pathlib import Path


async def run_setup(args) -> None:
    """Interactive setup wizard."""
    print("\n\U0001f35e BreadMind Setup Wizard")
    print("=" * 40)

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

    print("\n\u2705 Setup complete!")
    print(f"   Config: {config_dir}")
    print("   Run: breadmind web")


def _ensure_config_dir() -> str:
    """Ensure config directory exists and return its path."""
    from breadmind.config import get_default_config_dir

    config_dir = get_default_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    print(f"\n\U0001f4c1 Config directory: {config_dir}")
    return config_dir


async def _setup_provider() -> tuple[str, str, str]:
    """Select LLM provider, enter API key, and choose model."""
    from breadmind.llm.factory import get_provider_options

    options = get_provider_options()

    print("\n\U0001f4e1 Select LLM Provider:")
    for i, opt in enumerate(options, 1):
        free = " (free)" if opt.get("free_tier") else ""
        print(f"  {i}. {opt['name']}{free}")

    while True:
        choice = input(f"\nChoice (1-{len(options)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                break
        except ValueError:
            pass
        print("Invalid choice.")

    selected = options[idx]
    provider_name = selected["id"]

    # API Key input
    api_key = ""
    if selected.get("env_key"):
        # Check if key already exists in environment
        existing = os.environ.get(selected["env_key"], "")
        if existing:
            masked = existing[:8] + "..." + existing[-4:]
            use_existing = input(
                f"\n\U0001f511 Found existing key: {masked}. Use it? (y/n): "
            ).strip().lower()
            if use_existing in ("y", "yes", ""):
                api_key = existing

        if not api_key:
            if selected.get("signup_url"):
                print(f"\n\U0001f517 Get API key: {selected['signup_url']}")
            api_key = input(f"\U0001f511 Enter {selected['env_key']}: ").strip()

    # Model selection
    models = selected.get("models", [])
    model = models[0] if models else ""
    if len(models) > 1:
        print("\n\U0001f4e6 Available models:")
        for i, m in enumerate(models, 1):
            print(f"  {i}. {m}")
        choice = input(f"Choice (1-{len(models)}, default=1): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model = models[idx]
        except (ValueError, IndexError):
            pass

    return provider_name, api_key, model


async def _verify_api_key(provider_name: str, api_key: str, model: str) -> None:
    """Verify API key with a health check."""
    print(f"\n\U0001f50d Verifying {provider_name} API key...", end=" ", flush=True)
    try:
        from breadmind.llm.factory import _PROVIDER_REGISTRY

        info = _PROVIDER_REGISTRY.get(provider_name)
        if info and api_key:
            provider = info.cls(api_key=api_key, default_model=model)
            ok = await provider.health_check()
            if ok:
                print("\u2713")
            else:
                print("\u2717 (key may be invalid)")
        else:
            print("skipped")
    except Exception as e:
        print(f"\u2717 ({e})")


async def _setup_database() -> str | None:
    """Configure PostgreSQL connection (optional)."""
    print("\n\U0001f5c4\ufe0f  PostgreSQL Setup (optional, enables memory persistence)")
    use_db = input("   Configure PostgreSQL? (y/n, default=n): ").strip().lower()
    if use_db not in ("y", "yes"):
        print("   Skipped \u2014 using file-based storage.")
        return None

    dsn = input(
        "   DSN (e.g., postgresql://user:pass@localhost:5432/breadmind): "
    ).strip()
    if not dsn:
        print("   Skipped.")
        return None

    # Test connection
    print("   Testing connection...", end=" ", flush=True)
    try:
        import asyncpg  # noqa: F811

        conn = await asyncpg.connect(dsn)
        await conn.execute("SELECT 1")
        await conn.close()
        print("\u2713")
        return dsn
    except ImportError:
        print("\u2717 (asyncpg not installed: pip install asyncpg)")
        return None
    except Exception as e:
        print(f"\u2717 ({e})")
        return None


def _write_config(
    config_dir: str,
    provider: str,
    model: str,
    db_dsn: str | None,
) -> None:
    """Generate config.yaml."""
    config_path = os.path.join(config_dir, "config.yaml")
    if os.path.exists(config_path):
        overwrite = input(
            f"\n   {config_path} exists. Overwrite? (y/n): "
        ).strip().lower()
        if overwrite not in ("y", "yes"):
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
    print(f"   Written: {config_path}")


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
        Path(env_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"   Written: {env_path}")


async def _test_chat(provider_name: str, api_key: str, model: str) -> None:
    """Run a quick test chat to verify everything works end-to-end."""
    print("\n\U0001f9ea Test chat...")
    try:
        from breadmind.llm.factory import _PROVIDER_REGISTRY
        from breadmind.llm.base import LLMMessage

        info = _PROVIDER_REGISTRY.get(provider_name)
        if not info or not api_key:
            print("   Skipped (no provider/key)")
            return

        provider = info.cls(api_key=api_key, default_model=model)
        response = await provider.chat(
            [LLMMessage(role="user", content="Say 'Hello from BreadMind!' in one line.")]
        )
        print(f"   Response: {response.content}")
        print(f"   Tokens: {response.usage.total_tokens}")
        await provider.close()
    except Exception as e:
        print(f"   Test failed: {e}")
