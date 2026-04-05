"""Tests for Pydantic v2 config models."""

import pytest
from pydantic import ValidationError

from breadmind.config import (
    AppConfig,
    DatabaseConfig,
    LLMConfig,
    MCPConfig,
    NetworkConfig,
    SecurityConfig,
    WebConfig,
)
from breadmind.config_types import (
    EmbeddingConfig,
    LimitsConfig,
    MemoryGCConfig,
    PollingConfig,
    RetryConfig,
    TimeoutsConfig,
)
from breadmind.constants import (
    DEFAULT_DB_HOST,
    DEFAULT_DB_PORT,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
)


class TestWebConfig:
    def test_defaults(self):
        cfg = WebConfig()
        assert cfg.port == DEFAULT_WEB_PORT
        assert cfg.host == DEFAULT_WEB_HOST

    def test_extra_fields_ignored(self):
        cfg = WebConfig(host="0.0.0.0", unknown_field="ignored")
        assert cfg.host == "0.0.0.0"
        assert not hasattr(cfg, "unknown_field")

    def test_validation_rejects_invalid_type(self):
        with pytest.raises(ValidationError):
            WebConfig(port="not_a_number")

    def test_mutation(self):
        cfg = WebConfig()
        cfg.port = 9090
        assert cfg.port == 9090


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.default_model == DEFAULT_MODEL
        assert cfg.default_provider == DEFAULT_PROVIDER

    def test_mutation(self):
        cfg = LLMConfig()
        cfg.default_model = "gpt-4"
        assert cfg.default_model == "gpt-4"


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.host == DEFAULT_DB_HOST
        assert cfg.port == DEFAULT_DB_PORT

    def test_dsn_without_password_raises(self):
        import os
        old = os.environ.pop("BREADMIND_DB_PASSWORD", None)
        try:
            cfg = DatabaseConfig()
            with pytest.raises(ValueError, match="password is not configured"):
                _ = cfg.dsn
        finally:
            if old is not None:
                os.environ["BREADMIND_DB_PASSWORD"] = old

    def test_dsn_with_password(self):
        cfg = DatabaseConfig(password="secret")
        assert "secret" in cfg.dsn
        assert cfg.dsn.startswith("postgresql://")


class TestSecurityConfig:
    def test_defaults(self):
        cfg = SecurityConfig()
        assert cfg.auth_enabled is False
        assert isinstance(cfg.cors_origins, list)

    def test_extra_ignored(self):
        cfg = SecurityConfig(extra_field="value")
        assert not hasattr(cfg, "extra_field")


class TestNetworkConfig:
    def test_defaults(self):
        cfg = NetworkConfig()
        assert cfg.mode == "standalone"


class TestMCPConfig:
    def test_default_registries(self):
        cfg = MCPConfig()
        assert len(cfg.registries) == 3
        assert cfg.registries[0].name == "skills.sh"

    def test_mutation(self):
        cfg = MCPConfig()
        cfg.auto_discover = False
        assert cfg.auto_discover is False


class TestConfigTypes:
    def test_memory_gc_defaults(self):
        cfg = MemoryGCConfig()
        assert cfg.decay_threshold == 0.1

    def test_timeouts_defaults(self):
        cfg = TimeoutsConfig()
        assert cfg.health_check == 5

    def test_retry_defaults(self):
        cfg = RetryConfig()
        assert cfg.health_check_interval == 30

    def test_limits_defaults(self):
        cfg = LimitsConfig()
        assert cfg.max_per_domain_skills == 1

    def test_polling_defaults(self):
        cfg = PollingConfig()
        assert cfg.signal_interval == 5

    def test_embedding_provider_defaults(self):
        cfg = EmbeddingConfig()
        assert cfg.PROVIDER_DEFAULTS is not None
        assert "fastembed" in cfg.PROVIDER_DEFAULTS

    def test_mutation_via_setattr(self):
        cfg = TimeoutsConfig()
        setattr(cfg, "health_check", 10)
        assert cfg.health_check == 10


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert isinstance(cfg.llm, LLMConfig)
        assert isinstance(cfg.web, WebConfig)
        assert isinstance(cfg.database, DatabaseConfig)
        assert isinstance(cfg.security, SecurityConfig)

    def test_persona_private_attr(self):
        cfg = AppConfig()
        assert cfg._persona is None
        cfg._persona = {"name": "Test", "preset": "friendly"}
        assert cfg._persona["name"] == "Test"

    def test_nested_mutation(self):
        cfg = AppConfig()
        cfg.llm.default_model = "test-model"
        assert cfg.llm.default_model == "test-model"

    def test_extra_fields_ignored(self):
        cfg = AppConfig(unknown_section="ignored")
        assert not hasattr(cfg, "unknown_section")

    def test_model_dump(self):
        cfg = AppConfig()
        data = cfg.model_dump()
        assert "llm" in data
        assert "web" in data
        assert "database" in data

    def test_validate_method(self):
        cfg = AppConfig()
        # Should not raise with defaults
        cfg.validate()

    def test_validate_bad_log_level(self):
        cfg = AppConfig()
        cfg.logging.level = "INVALID"
        with pytest.raises(ValueError, match="Invalid log level"):
            cfg.validate()
