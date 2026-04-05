"""Tests for Pydantic config schema validation layer.

After unification, config_schema.py delegates to the Pydantic BaseModel
classes in breadmind.config.  These tests verify the validate_config()
helper works correctly with the unified models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from breadmind.core.config_schema import (
    AppConfigSchema,
    validate_config,
)
from breadmind.config import (
    AppConfig,
    DatabaseConfig,
    LLMConfig,
    LoggingConfig,
    WebConfig,
)


# -- Fixtures ----------------------------------------------------------------


def _minimal_valid_config() -> dict:
    """Return a minimal dictionary that passes validation."""
    return {
        "database": {
            "host": "localhost",
            "port": 5432,
            "name": "breadmind",
            "user": "breadmind",
        },
        "llm": {
            "default_provider": "gemini",
            "default_model": "gemini-2.5-flash",
            "tool_call_max_turns": 20,
            "tool_call_timeout_seconds": 30,
        },
        "web": {"host": "0.0.0.0", "port": 8080},
        "logging": {"level": "INFO", "format": "json"},
        "security": {"auth_enabled": False},
        "network": {"mode": "standalone"},
    }


# -- Tests -------------------------------------------------------------------


def test_valid_config():
    """A well-formed configuration dict should pass validation."""
    cfg = _minimal_valid_config()
    schema = validate_config(cfg)
    assert isinstance(schema, AppConfigSchema)
    assert schema.database.port == 5432
    assert schema.llm.default_provider == "gemini"


def test_invalid_port_type():
    """Port with non-numeric type must be rejected."""
    cfg = _minimal_valid_config()
    cfg["database"]["port"] = "not_a_number"
    with pytest.raises(ValidationError):
        validate_config(cfg)


def test_missing_required_fields():
    """All schemas have defaults, so an empty dict should pass."""
    schema = validate_config({})
    assert isinstance(schema, AppConfigSchema)
    assert schema.database.host == "localhost"
    assert schema.llm.default_provider == "gemini"


def test_extra_fields_ignored():
    """Unknown top-level fields are silently ignored (extra='ignore')."""
    cfg = _minimal_valid_config()
    cfg["unknown_section"] = {"foo": "bar"}
    # Should NOT raise — extra fields are ignored
    schema = validate_config(cfg)
    assert isinstance(schema, AppConfigSchema)


def test_extra_fields_ignored_nested():
    """Unknown nested fields are also silently ignored."""
    cfg = _minimal_valid_config()
    cfg["database"]["connection_pool_size"] = 10
    # Should NOT raise — extra fields are ignored
    schema = validate_config(cfg)
    assert schema.database.host == "localhost"


def test_validate_config_dict():
    """validate_config must accept a plain dict and return AppConfigSchema."""
    result = validate_config({"web": {"port": 9090, "host": "0.0.0.0"}})
    assert isinstance(result, AppConfigSchema)
    assert result.web.port == 9090
    assert result.web.host == "0.0.0.0"
    # Other sections should have defaults
    assert result.database.host == "localhost"


def test_app_config_schema_is_app_config():
    """AppConfigSchema should be the same as AppConfig after unification."""
    assert AppConfigSchema is AppConfig


def test_database_config_standalone():
    """DatabaseConfig standalone validation."""
    db = DatabaseConfig(host="db.example.com", port=5433, name="mydb", user="admin")
    assert db.host == "db.example.com"
    assert db.port == 5433


def test_web_config_defaults():
    """WebConfig defaults."""
    w = WebConfig()
    assert w.host == "127.0.0.1"
    assert w.port == 8080


def test_logging_config():
    """LoggingConfig accepts any string for level/format (validated separately)."""
    cfg = LoggingConfig(level="DEBUG", format="text")
    assert cfg.level == "DEBUG"
    assert cfg.format == "text"


def test_llm_config_defaults():
    """LLMConfig default values."""
    llm = LLMConfig()
    assert llm.tool_call_max_turns == 20
    assert llm.default_provider == "gemini"
