import os
import platform
import yaml
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from breadmind.constants import (
    DEFAULT_DB_HOST,
    DEFAULT_DB_NAME,
    DEFAULT_DB_PORT,
    DEFAULT_DB_USER,
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_MODEL,
    DEFAULT_OFFLINE_THRESHOLD,
    DEFAULT_PROVIDER,
    DEFAULT_REDIS_URL,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_TOOL_TIMEOUT,
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
    DEFAULT_WS_PORT,
)
from breadmind.config_types import (
    EmbeddingConfig,
    MemoryGCConfig,
    TimeoutsConfig,
    RetryConfig,
    LimitsConfig,
    PollingConfig,
)

def _get_valid_providers() -> tuple[str, ...]:
    try:
        from breadmind.llm.factory import get_valid_provider_names
        return get_valid_provider_names()
    except ImportError:
        return ("claude", "gemini", "grok", "ollama", "cli")

_VALID_PROVIDERS = _get_valid_providers()
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class WebConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    port: int = DEFAULT_WEB_PORT
    host: str = DEFAULT_WEB_HOST


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    level: str = "INFO"
    format: str = "json"


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    default_provider: str = DEFAULT_PROVIDER
    default_model: str = DEFAULT_MODEL
    tool_call_max_turns: int = 20
    tool_call_timeout_seconds: int = DEFAULT_TOOL_TIMEOUT


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    host: str = DEFAULT_DB_HOST
    port: int = DEFAULT_DB_PORT
    name: str = DEFAULT_DB_NAME
    user: str = DEFAULT_DB_USER
    password: str = ""

    @property
    def dsn(self) -> str:
        pw = self.password
        if not pw:
            pw = os.environ.get("BREADMIND_DB_PASSWORD", "")
        if not pw:
            raise ValueError(
                "Database password is not configured. "
                "Set 'password' in config.yaml or the BREADMIND_DB_PASSWORD environment variable."
            )
        return f"postgresql://{self.user}:{pw}@{self.host}:{self.port}/{self.name}"


class RegistryConfigItem(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    name: str
    type: str
    enabled: bool = True
    url: str | None = None


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    auto_discover: bool = True
    max_restart_attempts: int = 3
    servers: dict = Field(default_factory=dict)
    registries: list[RegistryConfigItem] = Field(default_factory=lambda: [
        RegistryConfigItem(name="skills.sh", type="skills_sh", enabled=True,
                           url="https://skills.sh"),
        RegistryConfigItem(name="clawhub", type="clawhub", enabled=True),
        RegistryConfigItem(name="mcp-registry", type="mcp_registry", enabled=True,
                           url="https://registry.modelcontextprotocol.io"),
    ])


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    auth_enabled: bool = False
    password_hash: str = ""  # SHA-256 hash
    api_keys: list[str] = Field(default_factory=list)
    session_timeout: int = DEFAULT_SESSION_TIMEOUT  # 2 hours
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8080", "http://127.0.0.1:8080"])
    require_https: bool = False


class TaskConfig(BaseModel):
    """Background task system configuration (Celery + Redis)."""
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    redis_url: str = DEFAULT_REDIS_URL
    max_concurrent_monitors: int = 10
    result_max_size_kb: int = 100
    completed_retention_days: int = 30


class NetworkConfig(BaseModel):
    """Distributed agent network configuration."""
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    mode: str = "standalone"  # standalone | commander | worker
    commander_url: str = ""  # Worker: wss://commander:8081/ws/agent/self
    ws_port: int = DEFAULT_WS_PORT  # Commander: WebSocket hub port
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL  # seconds
    offline_threshold: int = DEFAULT_OFFLINE_THRESHOLD  # seconds without heartbeat -> offline
    ca_cert_path: str = ""
    ca_key_path: str = ""
    cert_path: str = ""
    key_path: str = ""
    ca_passphrase_env: str = "BREADMIND_CA_PASSPHRASE"
    llm_proxy_rpm: int = 30  # per-worker requests per minute
    llm_proxy_rph: int = 500  # per-worker requests per hour
    offline_queue_max_rows: int = 10000
    offline_queue_max_mb: int = 100


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    polling: PollingConfig = Field(default_factory=PollingConfig)
    memory_gc: MemoryGCConfig = Field(default_factory=MemoryGCConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    # PrivateAttr: existing code accesses config._persona directly.
    # Pydantic treats underscore-prefixed names as private attributes.
    _persona: dict[str, Any] | None = PrivateAttr(default=None)

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


DEFAULT_PERSONA = {
    "name": "BreadMind",
    "preset": "professional",
    "language": "ko",
    "specialties": [],
}

# Backward-compatible alias — persona presets are now in prompts/personas/*.j2
# but some web routes may still reference this dict.
DEFAULT_PERSONA_PRESETS = {
    "professional": "professional",
    "friendly": "friendly",
    "concise": "concise",
    "humorous": "humorous",
}


def build_system_prompt(persona: dict, behavior_prompt: str | None = None) -> str:
    """Legacy helper — delegates to PromptBuilder when available.

    Kept for backward compatibility. New code should use PromptBuilder directly.
    """
    try:
        from breadmind.prompts.builder import PromptBuilder, PromptContext
        from pathlib import Path
        import platform as _plat
        from datetime import datetime, timezone

        prompts_dir = Path(__file__).resolve().parent / "prompts"
        builder = PromptBuilder(prompts_dir, lambda t: len(t) // 4)
        ctx = PromptContext(
            persona_name=persona.get("name", "BreadMind"),
            language=persona.get("language", "ko"),
            specialties=persona.get("specialties", []),
            os_info=f"{_plat.system()} {_plat.release()} ({_plat.machine()})",
            current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            custom_instructions=behavior_prompt,
        )
        return builder.build(
            provider="claude",
            persona=persona.get("preset", "professional"),
            context=ctx,
        )
    except Exception:
        # Ultimate fallback
        from breadmind.prompts.builder import FALLBACK_PROMPT
        return FALLBACK_PROMPT


def get_default_config_dir() -> str:
    """Return platform-specific default config directory."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "breadmind")
    elif system == "Darwin":
        return os.path.expanduser("~/.config/breadmind")
    else:  # Linux and others
        return os.path.expanduser("~/.config/breadmind")


def load_config(config_dir: str = "config") -> AppConfig:
    config_path = Path(config_dir) / "config.yaml"
    if not config_path.exists():
        return AppConfig()

    # When BREADMIND_ENV is explicitly set, load environment-specific profile
    # and deep-merge it on top of the base config.yaml.
    if os.environ.get("BREADMIND_ENV"):
        from breadmind.core.config_profiles import load_with_profile
        raw = load_with_profile(config_dir)
    else:
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
    security_raw = raw.get("security", {})
    logging_raw = raw.get("logging", {})

    # New config sections (with defaults if absent)
    memory_gc_raw = raw.get("memory", {}).get("gc", {})
    timeouts_raw = raw.get("timeouts", {})
    retry_raw = raw.get("retry", {})
    limits_raw = raw.get("limits", {})
    polling_raw = raw.get("polling", {})

    # Pydantic models with extra="ignore" handle unknown fields automatically,
    # so we can pass the raw dicts directly without filtering by field names.
    config = AppConfig(
        llm=LLMConfig(**llm_raw),
        database=DatabaseConfig(**{k: (int(v) if k == "port" else v) for k, v in db_raw.items()}),
        mcp=mcp_config,
        web=WebConfig(**web_raw),
        security=SecurityConfig(**security_raw),
        logging=LoggingConfig(**logging_raw),
        memory_gc=MemoryGCConfig(**memory_gc_raw),
        timeouts=TimeoutsConfig(**timeouts_raw),
        retry=RetryConfig(**retry_raw),
        limits=LimitsConfig(**limits_raw),
        polling=PollingConfig(**polling_raw),
    )

    # CORS origins from environment variable (comma-separated, overrides config file)
    env_cors = os.environ.get("BREADMIND_CORS_ORIGINS")
    if env_cors:
        config.security.cors_origins = [o.strip() for o in env_cors.split(",")]

    # Redis URL for background tasks
    redis_url = os.environ.get("BREADMIND_REDIS_URL")
    if redis_url:
        config.task.redis_url = redis_url

    return config


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


# Re-export env/secrets functions for backward compatibility.
# Implementation lives in config_env.py.
from breadmind.config_env import (  # noqa: F401, E402
    _VALID_API_KEY_NAMES,
    set_env_file_path,
    encrypt_value,
    decrypt_value,
    save_env_var,
    load_env_file,
    save_api_key_to_db,
    load_api_keys_from_db,
)


async def apply_db_settings(config: AppConfig, db) -> dict:
    """Load settings from DB and apply to config, overriding file-based defaults.

    Returns a dict of extra settings that have no direct config field,
    so callers can use them without additional DB queries.
    """
    extra: dict = {}
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

        # Load persona
        persona = await db.get_setting("persona")
        if persona:
            config.persona = persona
        else:
            config.persona = DEFAULT_PERSONA

        # Load encrypted API keys
        await load_api_keys_from_db(db)

        # Skill markets restoration
        saved_markets = await db.get_setting("skill_markets")
        if saved_markets and isinstance(saved_markets, list):
            config.mcp.registries = [
                RegistryConfigItem(
                    name=m.get("name", ""),
                    type=m.get("type", ""),
                    enabled=m.get("enabled", True),
                    url=m.get("url") or None,
                )
                for m in saved_markets if m.get("name")
            ]

        # Load extra settings (safety, scheduler, webhook, monitoring, etc.)
        _EXTRA_SETTING_KEYS = (
            "safety_blacklist", "safety_approval", "safety_permissions",
            "scheduler_cron", "scheduler_heartbeat",
            "webhook_endpoints", "monitoring_config", "memory_config",
            "tool_security", "agent_timeouts", "logging_config",
        )
        for setting_key in _EXTRA_SETTING_KEYS:
            extra[setting_key] = await db.get_setting(setting_key)

        # Messenger token restoration
        for token_key in ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "DISCORD_BOT_TOKEN",
                          "TELEGRAM_BOT_TOKEN", "WHATSAPP_TWILIO_ACCOUNT_SID",
                          "WHATSAPP_TWILIO_AUTH_TOKEN", "GMAIL_CLIENT_ID",
                          "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
                          "SIGNAL_PHONE_NUMBER"]:
            try:
                data = await db.get_setting(f"messenger_token:{token_key}")
                if data and "value" in data:
                    os.environ.setdefault(token_key, data["value"])
            except Exception:
                pass

        # System timeouts (UI-managed)
        system_timeouts = await db.get_setting("system_timeouts")
        if system_timeouts and isinstance(system_timeouts, dict):
            for key, value in system_timeouts.items():
                if hasattr(config.timeouts, key):
                    setattr(config.timeouts, key, value)

        # Retry settings (UI-managed)
        retry_config = await db.get_setting("retry_config")
        if retry_config and isinstance(retry_config, dict):
            for key, value in retry_config.items():
                if hasattr(config.retry, key):
                    setattr(config.retry, key, value)

        # Limits settings (UI-managed)
        limits_config = await db.get_setting("limits_config")
        if limits_config and isinstance(limits_config, dict):
            for key, value in limits_config.items():
                if hasattr(config.limits, key):
                    setattr(config.limits, key, value)

        # Polling settings (UI-managed)
        polling_config = await db.get_setting("polling_config")
        if polling_config and isinstance(polling_config, dict):
            for key, value in polling_config.items():
                if hasattr(config.polling, key):
                    setattr(config.polling, key, value)

        # Memory GC settings (UI-managed)
        memory_gc_config = await db.get_setting("memory_gc_config")
        if memory_gc_config and isinstance(memory_gc_config, dict):
            for key, value in memory_gc_config.items():
                if hasattr(config.memory_gc, key):
                    setattr(config.memory_gc, key, value)

        # Embedding settings (UI-managed)
        embedding_config = await db.get_setting("embedding_config")
        if embedding_config and isinstance(embedding_config, dict):
            for key in ("provider", "model_name", "ollama_base_url", "cache_size"):
                if key in embedding_config:
                    setattr(config.embedding, key, embedding_config[key])

    except Exception:
        pass  # DB not available, use file-based config
    return extra


def load_safety_config(config_dir: str = "config") -> dict:
    safety_path = Path(config_dir) / "safety.yaml"
    if not safety_path.exists():
        return {"blacklist": {}, "require_approval": []}
    with open(safety_path) as f:
        return yaml.safe_load(f) or {}
