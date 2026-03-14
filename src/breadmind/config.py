import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

_VALID_PROVIDERS = ("claude", "gemini", "ollama", "cli")
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class WebConfig:
    port: int = 8080
    host: str = "0.0.0.0"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"


@dataclass
class LLMConfig:
    default_provider: str = "claude"
    default_model: str = "claude-sonnet-4-6"
    fallback_chain: list[str] = field(default_factory=lambda: ["claude", "ollama"])
    tool_call_max_turns: int = 10
    tool_call_timeout_seconds: int = 30


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "breadmind"
    user: str = "breadmind"
    password: str = "breadmind_dev"

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class RegistryConfigItem:
    name: str
    type: str
    enabled: bool = True
    url: str | None = None


@dataclass
class MCPConfig:
    auto_discover: bool = True
    max_restart_attempts: int = 3
    servers: dict = field(default_factory=dict)
    registries: list[RegistryConfigItem] = field(default_factory=lambda: [
        RegistryConfigItem(name="clawhub", type="clawhub", enabled=True),
        RegistryConfigItem(name="mcp-registry", type="mcp_registry", enabled=True,
                           url="https://registry.modelcontextprotocol.io"),
    ])


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> None:
        if self.llm.default_provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid default_provider '{self.llm.default_provider}', "
                f"must be one of {list(_VALID_PROVIDERS)}"
            )
        if self.llm.tool_call_max_turns < 1:
            raise ValueError(
                f"tool_call_max_turns must be >= 1, got {self.llm.tool_call_max_turns}"
            )
        if self.llm.tool_call_timeout_seconds < 1:
            raise ValueError(
                f"tool_call_timeout_seconds must be >= 1, got {self.llm.tool_call_timeout_seconds}"
            )
        if not (1 <= self.database.port <= 65535):
            raise ValueError(
                f"Database port must be between 1 and 65535, got {self.database.port}"
            )
        if not (1 <= self.web.port <= 65535):
            raise ValueError(
                f"Web port must be between 1 and 65535, got {self.web.port}"
            )
        if self.logging.level not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log level '{self.logging.level}', "
                f"must be one of {list(_VALID_LOG_LEVELS)}"
            )


def load_config(config_dir: str = "config") -> AppConfig:
    config_path = Path(config_dir) / "config.yaml"
    if not config_path.exists():
        return AppConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # Expand env vars
    raw = _expand_env(raw)

    llm_raw = raw.get("llm", {})
    db_raw = raw.get("database", {})

    mcp_raw = raw.get("mcp", {})
    mcp_config = MCPConfig()
    if mcp_raw:
        mcp_config.auto_discover = mcp_raw.get("auto_discover", True)
        mcp_config.max_restart_attempts = mcp_raw.get("max_restart_attempts", 3)
        mcp_config.servers = mcp_raw.get("servers", {})
        if "registries" in mcp_raw:
            mcp_config.registries = [
                RegistryConfigItem(**r) for r in mcp_raw["registries"]
            ]

    web_raw = raw.get("web", {})
    logging_raw = raw.get("logging", {})

    return AppConfig(
        llm=LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}),
        database=DatabaseConfig(**{k: v for k, v in db_raw.items() if k in DatabaseConfig.__dataclass_fields__}),
        mcp=mcp_config,
        web=WebConfig(**{k: v for k, v in web_raw.items() if k in WebConfig.__dataclass_fields__}),
        logging=LoggingConfig(**{k: v for k, v in logging_raw.items() if k in LoggingConfig.__dataclass_fields__}),
    )


def _expand_env(obj):
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        var = obj[2:-1]
        default = None
        if ":-" in var:
            var, default = var.split(":-", 1)
        return os.environ.get(var, default or "")
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


_VALID_API_KEY_NAMES = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")


def _get_or_create_master_key() -> bytes:
    """Get master encryption key from env, or generate and save one."""
    key_str = os.environ.get("BREADMIND_MASTER_KEY", "")
    if key_str:
        return key_str.encode()
    # Auto-generate and save to .env
    from cryptography.fernet import Fernet
    new_key = Fernet.generate_key()
    save_env_var("BREADMIND_MASTER_KEY", new_key.decode())
    return new_key


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string using Fernet symmetric encryption."""
    from cryptography.fernet import Fernet
    key = _get_or_create_master_key()
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    from cryptography.fernet import Fernet
    key = _get_or_create_master_key()
    f = Fernet(key)
    return f.decrypt(ciphertext.encode()).decode()


def save_env_var(key: str, value: str):
    """Save/update an environment variable to .env file."""
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
    env_path.write_text("\n".join(lines) + "\n")
    # Also set in current process
    os.environ[key] = value


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
    for key_name in _VALID_API_KEY_NAMES:
        try:
            data = await db.get_setting(f"apikey:{key_name}")
            if data and "encrypted" in data:
                plaintext = decrypt_value(data["encrypted"])
                os.environ[key_name] = plaintext
        except Exception:
            pass  # Key not found or decryption failed


async def apply_db_settings(config: AppConfig, db) -> None:
    """Load settings from DB and apply to config, overriding file-based defaults."""
    try:
        llm_settings = await db.get_setting("llm")
        if llm_settings:
            if "default_provider" in llm_settings:
                config.llm.default_provider = llm_settings["default_provider"]
            if "default_model" in llm_settings:
                config.llm.default_model = llm_settings["default_model"]
            if "tool_call_max_turns" in llm_settings:
                config.llm.tool_call_max_turns = llm_settings["tool_call_max_turns"]
            if "tool_call_timeout_seconds" in llm_settings:
                config.llm.tool_call_timeout_seconds = llm_settings["tool_call_timeout_seconds"]

        mcp_settings = await db.get_setting("mcp")
        if mcp_settings:
            if "auto_discover" in mcp_settings:
                config.mcp.auto_discover = mcp_settings["auto_discover"]
            if "max_restart_attempts" in mcp_settings:
                config.mcp.max_restart_attempts = mcp_settings["max_restart_attempts"]

        # Load encrypted API keys
        await load_api_keys_from_db(db)
    except Exception:
        pass  # DB not available, use file-based config


def load_safety_config(config_dir: str = "config") -> dict:
    safety_path = Path(config_dir) / "safety.yaml"
    if not safety_path.exists():
        return {"blacklist": {}, "require_approval": []}
    with open(safety_path) as f:
        return yaml.safe_load(f) or {}
