"""Tests for Pydantic config schema validation layer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from breadmind.core.config_schema import (
    AppConfigSchema,
    DatabaseSchema,
    LLMSchema,
    LoggingSchema,
    SafetySchema,
    WebSchema,
    validate_config,
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
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "max_turns": 20,
            "timeout": 30,
        },
        "web": {"host": "0.0.0.0", "port": 8080},
        "logging": {"level": "INFO", "format": "json"},
        "safety": {"autonomy": "confirm-unsafe", "blocked_patterns": []},
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
    assert schema.llm.provider == "gemini"


def test_invalid_port():
    """Port numbers outside 1-65535 must be rejected."""
    cfg = _minimal_valid_config()
    cfg["database"]["port"] = 70000
    with pytest.raises(ValidationError) as exc_info:
        validate_config(cfg)
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("database", "port") for e in errors)


def test_invalid_port_zero():
    """Port 0 must be rejected."""
    cfg = _minimal_valid_config()
    cfg["web"]["port"] = 0
    with pytest.raises(ValidationError):
        validate_config(cfg)


def test_invalid_provider():
    """An unsupported LLM provider name must be rejected."""
    cfg = _minimal_valid_config()
    cfg["llm"]["provider"] = "chatgpt"
    with pytest.raises(ValidationError) as exc_info:
        validate_config(cfg)
    errors = exc_info.value.errors()
    assert any("provider" in str(e["loc"]) for e in errors)


def test_invalid_log_level():
    """Invalid log levels must be rejected."""
    cfg = _minimal_valid_config()
    cfg["logging"]["level"] = "VERBOSE"
    with pytest.raises(ValidationError) as exc_info:
        validate_config(cfg)
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("logging", "level") for e in errors)


def test_extra_fields_rejected():
    """Unknown top-level fields must be rejected (extra='forbid')."""
    cfg = _minimal_valid_config()
    cfg["unknown_section"] = {"foo": "bar"}
    with pytest.raises(ValidationError) as exc_info:
        validate_config(cfg)
    errors = exc_info.value.errors()
    assert any("unknown_section" in str(e["loc"]) for e in errors)


def test_extra_fields_rejected_nested():
    """Unknown nested fields must also be rejected."""
    cfg = _minimal_valid_config()
    cfg["database"]["connection_pool_size"] = 10
    with pytest.raises(ValidationError):
        validate_config(cfg)


def test_missing_required_fields():
    """All schemas have defaults, so an empty dict should pass."""
    schema = validate_config({})
    assert isinstance(schema, AppConfigSchema)
    assert schema.database.host == "localhost"
    assert schema.llm.provider == "gemini"


def test_secret_str_masking():
    """SecretStr fields must not expose their value via str() or repr()."""
    cfg = _minimal_valid_config()
    cfg["database"]["password"] = "super-secret-password"
    cfg["llm"]["api_key"] = "sk-secret-key-12345"
    schema = validate_config(cfg)

    # str/repr must not contain the actual secret
    db_str = str(schema.database.password)
    assert "super-secret-password" not in db_str
    assert "**" in db_str

    llm_str = str(schema.llm.api_key)
    assert "sk-secret-key-12345" not in llm_str
    assert "**" in llm_str

    # But get_secret_value() should return the real value
    assert schema.database.password.get_secret_value() == "super-secret-password"
    assert schema.llm.api_key.get_secret_value() == "sk-secret-key-12345"


def test_database_schema():
    """DatabaseSchema standalone validation."""
    db = DatabaseSchema(host="db.example.com", port=5433, name="mydb", user="admin")
    assert db.host == "db.example.com"
    assert db.port == 5433

    with pytest.raises(ValidationError):
        DatabaseSchema(port=-1)

    with pytest.raises(ValidationError):
        DatabaseSchema(port=99999)


def test_validate_config_dict():
    """validate_config must accept a plain dict and return AppConfigSchema."""
    result = validate_config({"web": {"port": 9090, "host": "0.0.0.0"}})
    assert isinstance(result, AppConfigSchema)
    assert result.web.port == 9090
    assert result.web.host == "0.0.0.0"
    # Other sections should have defaults
    assert result.database.host == "localhost"


def test_nested_validation_error():
    """Nested field errors must include the full dotted path."""
    cfg = _minimal_valid_config()
    cfg["llm"]["max_turns"] = -5
    cfg["database"]["port"] = 0

    with pytest.raises(ValidationError) as exc_info:
        validate_config(cfg)

    errors = exc_info.value.errors()
    locs = [e["loc"] for e in errors]
    # Should contain paths like ('llm', 'max_turns') and ('database', 'port')
    assert any("max_turns" in str(loc) for loc in locs)
    assert any("port" in str(loc) for loc in locs)
    # Error count should be at least 2
    assert len(errors) >= 2


def test_llm_schema_boundary_values():
    """Boundary values for LLM schema fields."""
    # max_turns=1 should be valid
    llm = LLMSchema(max_turns=1, timeout=1)
    assert llm.max_turns == 1

    # max_turns=100 should be valid
    llm = LLMSchema(max_turns=100)
    assert llm.max_turns == 100

    # max_turns=101 should fail
    with pytest.raises(ValidationError):
        LLMSchema(max_turns=101)

    # timeout=0 should fail
    with pytest.raises(ValidationError):
        LLMSchema(timeout=0)


def test_safety_schema():
    """SafetySchema autonomy mode validation."""
    s = SafetySchema(autonomy="auto", blocked_patterns=["rm -rf /"])
    assert s.autonomy == "auto"
    assert s.blocked_patterns == ["rm -rf /"]

    with pytest.raises(ValidationError):
        SafetySchema(autonomy="yolo")


def test_web_schema_cors_origins():
    """WebSchema cors_origins defaults and custom values."""
    w = WebSchema()
    assert len(w.cors_origins) == 2

    w2 = WebSchema(cors_origins=["https://example.com"])
    assert w2.cors_origins == ["https://example.com"]


def test_logging_schema_format():
    """LoggingSchema format must be 'text' or 'json'."""
    LoggingSchema(format="text")
    LoggingSchema(format="json")

    with pytest.raises(ValidationError):
        LoggingSchema(format="xml")
