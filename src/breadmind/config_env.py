"""Environment variable and secrets management for BreadMind.

Handles .env file I/O, master key management, and API key encryption/decryption.
Extracted from config.py for modularity.
"""
import os
from pathlib import Path

_VALID_API_KEY_NAMES = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY")

_env_file_path: str | None = None


def set_env_file_path(path: str):
    """Set the .env file path for save_env_var."""
    global _env_file_path
    _env_file_path = path


def _get_master_key() -> bytes:
    """Get master encryption key from env.

    In dev mode (BREADMIND_DEV=1), auto-generates a key if missing.
    In production, raises ValueError with instructions.
    """
    global _env_file_path
    key_str = os.environ.get("BREADMIND_MASTER_KEY", "")
    if key_str:
        return key_str.encode()

    # Dev mode: auto-generate and save (backward-compatible)
    if os.environ.get("BREADMIND_DEV") == "1":
        from cryptography.fernet import Fernet
        new_key = Fernet.generate_key()
        if _env_file_path:
            save_env_var("BREADMIND_MASTER_KEY", new_key.decode())
        else:
            from breadmind.config import get_default_config_dir
            default_path = os.path.join(get_default_config_dir(), ".env")
            Path(default_path).parent.mkdir(parents=True, exist_ok=True)
            old_path = _env_file_path
            _env_file_path = default_path
            save_env_var("BREADMIND_MASTER_KEY", new_key.decode())
            _env_file_path = old_path
        return new_key

    raise ValueError(
        "BREADMIND_MASTER_KEY is not set. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
        "and set it as the BREADMIND_MASTER_KEY environment variable."
    )


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string using Fernet symmetric encryption."""
    from cryptography.fernet import Fernet
    key = _get_master_key()
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    from cryptography.fernet import Fernet
    key = _get_master_key()
    f = Fernet(key)
    return f.decrypt(ciphertext.encode()).decode()


def save_env_var(key: str, value: str):
    """Save/update an environment variable to .env file."""
    if _env_file_path:
        env_path = Path(_env_file_path)
    else:
        env_path = Path(__file__).parent.parent.parent / ".env"
    lines = []
    found = False
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Restrict file permissions on Unix systems
    if os.name != "nt":
        os.chmod(env_path, 0o600)
    # Also set in current process
    os.environ[key] = value


def load_env_file(path: str):
    """Load environment variables from a .env file.
    Uses setdefault so existing env vars are not overwritten."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def save_api_key_to_db(db, key_name: str, plaintext_value: str):
    """Encrypt and save an API key to the database."""
    encrypted = encrypt_value(plaintext_value)
    await db.set_setting(f"apikey:{key_name}", {
        "encrypted": encrypted,
        "key_name": key_name,
    })
    # Also set in runtime environment
    os.environ[key_name] = plaintext_value


async def load_api_keys_from_db(db):
    """Load all encrypted API keys from DB and set in environment."""
    import logging
    logger = logging.getLogger(__name__)
    for key_name in _VALID_API_KEY_NAMES:
        try:
            data = await db.get_setting(f"apikey:{key_name}")
        except Exception as exc:
            logger.warning("load_api_keys_from_db: get_setting(%s) failed: %s", key_name, exc)
            continue
        if not data or "encrypted" not in data:
            continue
        try:
            plaintext = decrypt_value(data["encrypted"])
        except Exception as exc:
            logger.warning(
                "load_api_keys_from_db: decrypt failed for %s (%s: %s) — "
                "BREADMIND_MASTER_KEY may have changed since the key was stored",
                key_name, type(exc).__name__, exc,
            )
            continue
        os.environ[key_name] = plaintext
        logger.info("load_api_keys_from_db: hydrated %s from DB", key_name)
