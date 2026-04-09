"""Companion agent configuration: YAML-based, default paths per OS."""

from __future__ import annotations

import logging
import platform
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT = 30
_DEFAULT_RECONNECT_MAX_BACKOFF = 300


def _default_config_dir() -> Path:
    """Return platform-appropriate config directory."""
    system = platform.system()
    if system == "Windows":
        base = Path.home() / "AppData" / "Roaming"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        import os
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "breadmind-companion"


@dataclass
class CompanionConfig:
    commander_url: str = ""
    agent_id: str = ""
    device_name: str = ""
    heartbeat_interval: int = _DEFAULT_HEARTBEAT
    reconnect_max_backoff: int = _DEFAULT_RECONNECT_MAX_BACKOFF
    capabilities: dict[str, Any] = field(default_factory=dict)
    session_key: str = ""
    cert_path: str = ""
    key_path: str = ""
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.agent_id:
            self.agent_id = f"companion-{platform.node()}-{uuid.uuid4().hex[:8]}"
        if not self.device_name:
            self.device_name = platform.node()


def load_config(path: Path | None = None) -> CompanionConfig:
    """Load configuration from a YAML file."""
    if path is None:
        path = _default_config_dir() / "config.yaml"
    if not path.exists():
        logger.info("No config at %s, using defaults", path)
        return CompanionConfig()
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return CompanionConfig(**{k: v for k, v in data.items() if k in CompanionConfig.__dataclass_fields__})
    except Exception as e:
        logger.warning("Failed to load config from %s: %s", path, e)
        return CompanionConfig()


def save_config(config: CompanionConfig, path: Path | None = None) -> Path:
    """Save configuration to a YAML file. Returns the path written."""
    if path is None:
        path = _default_config_dir() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        from dataclasses import asdict
        data = asdict(config)
        path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        logger.info("Config saved to %s", path)
    except Exception as e:
        logger.error("Failed to save config to %s: %s", path, e)
        raise
    return path
