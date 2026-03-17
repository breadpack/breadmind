import os
import platform
import yaml
from dataclasses import dataclass, field
from pathlib import Path

def _get_valid_providers() -> tuple[str, ...]:
    try:
        from breadmind.llm.factory import get_valid_provider_names
        return get_valid_provider_names()
    except ImportError:
        return ("claude", "gemini", "grok", "ollama", "cli")

_VALID_PROVIDERS = _get_valid_providers()
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class WebConfig:
    port: int = 8080
    host: str = "127.0.0.1"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"


@dataclass
class LLMConfig:
    default_provider: str = "claude"
    default_model: str = "claude-sonnet-4-6"
    tool_call_max_turns: int = 10
    tool_call_timeout_seconds: int = 30


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "breadmind"
    user: str = "breadmind"
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
        RegistryConfigItem(name="skills.sh", type="skills_sh", enabled=True,
                           url="https://skills.sh"),
        RegistryConfigItem(name="clawhub", type="clawhub", enabled=True),
        RegistryConfigItem(name="mcp-registry", type="mcp_registry", enabled=True,
                           url="https://registry.modelcontextprotocol.io"),
    ])


@dataclass
class SecurityConfig:
    auth_enabled: bool = False
    password_hash: str = ""  # SHA-256 hash
    api_keys: list[str] = field(default_factory=list)
    session_timeout: int = 86400  # 24 hours
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8080", "http://127.0.0.1:8080"])
    require_https: bool = False


@dataclass
class NetworkConfig:
    """Distributed agent network configuration."""
    mode: str = "standalone"  # standalone | commander | worker
    commander_url: str = ""  # Worker: wss://commander:8081/ws/agent/self
    ws_port: int = 8081  # Commander: WebSocket hub port
    heartbeat_interval: int = 30  # seconds
    offline_threshold: int = 90  # seconds without heartbeat → offline
    ca_cert_path: str = ""
    ca_key_path: str = ""
    cert_path: str = ""
    key_path: str = ""
    ca_passphrase_env: str = "BREADMIND_CA_PASSPHRASE"
    llm_proxy_rpm: int = 30  # per-worker requests per minute
    llm_proxy_rph: int = 500  # per-worker requests per hour
    offline_queue_max_rows: int = 10000
    offline_queue_max_mb: int = 100


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    web: WebConfig = field(default_factory=WebConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    _persona: dict = field(default=None)

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


DEFAULT_PERSONA_PRESETS = {
    "professional": "You are BreadMind, a professional AI agent. Respond precisely and technically. Focus on accuracy and best practices.",
    "friendly": "You are BreadMind, a friendly AI agent. Explain things in an approachable way. Use simple language when possible.",
    "concise": "You are BreadMind, a concise AI agent. Keep responses brief and to the point. Minimize explanations unless asked.",
    "humorous": "You are BreadMind, a witty AI agent. Include light humor while being helpful. Keep it professional but fun.",
}

DEFAULT_PERSONA = {
    "name": "BreadMind",
    "preset": "professional",
    "system_prompt": DEFAULT_PERSONA_PRESETS["professional"],
    "language": "ko",
    "specialties": [],
}


_PROACTIVE_BEHAVIOR_PROMPT = """
## Core Behavior: Investigate → Act → Report

You MUST use tools before answering. Text-only responses are a last resort.

### Rules
1. **Investigate first.** DO NOT guess. Call tools to get live data.
2. **Chain tool calls.** If insufficient, call more tools.
3. **Execute, don't advise.** Perform actions via tools, never give instructions for the user to do it.
4. **Search when tools are missing.** Use mcp_search to find installable MCP skills.
5. **shell_exec as fallback.** When no specific tool exists, use shell commands.
6. **Report real results.** Summarize actual output. Never fabricate data.

### Autonomous Problem Solving (CRITICAL)
Solve problems autonomously. Do NOT ask clarifying questions unless absolutely necessary.

**Before asking the user, you MUST:**
- Investigate via tools (logs, configs, system state) to find the answer yourself.
- Try the most reasonable interpretation and execute it.
- If multiple approaches exist, pick the best one and proceed.

**Only ask when ALL are true:**
- Tool-based investigation is exhausted.
- The decision genuinely requires user input (credentials, choosing between fundamentally different goals, confirming destructive production actions).
- The question is specific and actionable.

**Never ask:** "어떻게 할까요?", "확인해 볼까요?", "더 자세한 정보를 주세요" — investigate and act instead.
""".strip()


def _get_os_context() -> str:
    """Detect current OS environment and return context string for the agent."""
    import platform as _plat
    system = _plat.system()
    release = _plat.release()
    machine = _plat.machine()

    if system == "Windows":
        shell_info = "Use PowerShell or cmd commands (e.g., Get-Process, Get-Service, ipconfig, systeminfo, wmic). Use shell_exec with powershell -Command for PowerShell commands."
    elif system == "Darwin":
        shell_info = "Use macOS commands (e.g., top, diskutil, networksetup, launchctl, sw_vers, system_profiler)."
    else:
        shell_info = "Use Linux commands (e.g., systemctl, ip, df, top, journalctl)."

    return (
        f"## Host Environment\n"
        f"- OS: {system} {release} ({machine})\n"
        f"- {shell_info}\n"
        f"- shell_exec runs directly on this host OS. Use OS-appropriate commands."
    )


def build_system_prompt(persona: dict, behavior_prompt: str | None = None) -> str:
    """Build full system prompt from persona config."""
    parts = [persona.get("system_prompt", DEFAULT_PERSONA["system_prompt"])]

    name = persona.get("name", "BreadMind")
    lang = persona.get("language", "ko")
    specialties = persona.get("specialties", [])

    if lang != "en":
        lang_names = {"ko": "Korean", "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "de": "German", "fr": "French"}
        parts.append(f"Always respond in {lang_names.get(lang, lang)}.")

    if specialties:
        parts.append(f"Your primary expertise areas: {', '.join(specialties)}.")

    parts.append(f"Your name is {name}.")

    # Append OS environment context
    parts.append(_get_os_context())

    # Append proactive execution behavior
    parts.append(behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT)

    return "\n\n".join(parts)


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

    return AppConfig(
        llm=LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}),
        database=DatabaseConfig(**{k: (int(v) if k == "port" else v) for k, v in db_raw.items() if k in DatabaseConfig.__dataclass_fields__}),
        mcp=mcp_config,
        web=WebConfig(**{k: v for k, v in web_raw.items() if k in WebConfig.__dataclass_fields__}),
        security=SecurityConfig(**{k: v for k, v in security_raw.items() if k in SecurityConfig.__dataclass_fields__}),
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


# Re-export env/secrets functions for backward compatibility.
# Implementation lives in config_env.py.
from breadmind.config_env import (  # noqa: F401
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
            config._persona = persona
        else:
            config._persona = DEFAULT_PERSONA

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
    except Exception:
        pass  # DB not available, use file-based config
    return extra


def load_safety_config(config_dir: str = "config") -> dict:
    safety_path = Path(config_dir) / "safety.yaml"
    if not safety_path.exists():
        return {"blacklist": {}, "require_approval": []}
    with open(safety_path) as f:
        return yaml.safe_load(f) or {}
