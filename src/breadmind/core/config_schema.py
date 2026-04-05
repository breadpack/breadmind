"""Pydantic v2 validation layer for BreadMind configuration.

This module provides strict schema validation on top of the existing
dataclass-based AppConfig.  It is opt-in: set the environment variable
``BREADMIND_VALIDATE_CONFIG=1`` to activate validation at load time.

Usage::

    from breadmind.core.config_schema import validate_config, validate_config_file

    schema = validate_config(raw_yaml_dict)
    schema = validate_config_file("config/config.yaml")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class DatabaseSchema(BaseModel):
    """Database connection settings."""

    model_config = ConfigDict(extra="forbid")

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = "breadmind"
    user: str = "breadmind"
    password: SecretStr | None = None


class LLMSchema(BaseModel):
    """LLM provider settings."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["claude", "gemini", "grok", "ollama", "cli"] = "gemini"
    model: str = "gemini-2.5-flash"
    api_key: SecretStr | None = None
    max_turns: int = Field(default=20, ge=1, le=100)
    timeout: int = Field(default=30, ge=1)


class WebSchema(BaseModel):
    """Web server binding settings."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8080", "http://127.0.0.1:8080"]
    )


class LoggingSchema(BaseModel):
    """Logging configuration."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["text", "json"] = "json"


class SafetySchema(BaseModel):
    """Safety guard configuration."""

    model_config = ConfigDict(extra="forbid")

    autonomy: Literal[
        "auto", "confirm-all", "confirm-unsafe", "confirm-destructive"
    ] = "confirm-unsafe"
    blocked_patterns: list[str] = Field(default_factory=list)


class SecuritySchema(BaseModel):
    """Security infrastructure settings."""

    model_config = ConfigDict(extra="forbid")

    auth_enabled: bool = False
    password_hash: str = ""
    api_keys: list[str] = Field(default_factory=list)
    session_timeout: int = 7200
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8080", "http://127.0.0.1:8080"]
    )
    require_https: bool = False


class NetworkSchema(BaseModel):
    """Distributed network mode settings."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["standalone", "commander", "worker"] = "standalone"
    commander_url: str = ""
    ws_port: int = Field(default=8081, ge=1, le=65535)
    heartbeat_interval: int = Field(default=30, ge=1)
    offline_threshold: int = Field(default=90, ge=1)


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------


class AppConfigSchema(BaseModel):
    """Top-level application configuration schema.

    Uses ``extra="forbid"`` so that unknown top-level keys cause a
    validation error, catching typos early.
    """

    model_config = ConfigDict(extra="forbid")

    database: DatabaseSchema = Field(default_factory=DatabaseSchema)
    llm: LLMSchema = Field(default_factory=LLMSchema)
    web: WebSchema = Field(default_factory=WebSchema)
    logging: LoggingSchema = Field(default_factory=LoggingSchema)
    safety: SafetySchema = Field(default_factory=SafetySchema)
    security: SecuritySchema = Field(default_factory=SecuritySchema)
    network: NetworkSchema = Field(default_factory=NetworkSchema)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def validate_config(raw_dict: dict) -> AppConfigSchema:
    """Validate a raw YAML dictionary against :class:`AppConfigSchema`.

    Parameters
    ----------
    raw_dict:
        A dictionary typically produced by ``yaml.safe_load()``.

    Returns
    -------
    AppConfigSchema
        The validated configuration object.

    Raises
    ------
    pydantic.ValidationError
        If validation fails.  The exception contains structured error
        details including the path to each invalid field.
    """
    try:
        return AppConfigSchema.model_validate(raw_dict)
    except ValidationError:
        logger.error("Configuration validation failed. Details follow.")
        raise


def validate_config_file(path: str | Path) -> AppConfigSchema:
    """Read a YAML config file and validate it.

    Parameters
    ----------
    path:
        Filesystem path to the YAML configuration file.

    Returns
    -------
    AppConfigSchema
        The validated configuration object.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    pydantic.ValidationError
        If the content fails schema validation.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as fh:
        raw = yaml.safe_load(fh) or {}

    return validate_config(raw)
