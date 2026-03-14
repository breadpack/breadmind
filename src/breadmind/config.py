import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

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
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

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

    return AppConfig(
        llm=LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}),
        database=DatabaseConfig(**{k: v for k, v in db_raw.items() if k in DatabaseConfig.__dataclass_fields__}),
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

def load_safety_config(config_dir: str = "config") -> dict:
    safety_path = Path(config_dir) / "safety.yaml"
    if not safety_path.exists():
        return {"blacklist": {}, "require_approval": []}
    with open(safety_path) as f:
        return yaml.safe_load(f) or {}
