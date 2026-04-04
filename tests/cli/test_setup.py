"""Tests for the interactive setup wizard (breadmind setup)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.cli.setup import (
    _ensure_config_dir,
    _setup_provider,
    _verify_api_key,
    _write_config,
    _write_env,
)


class TestEnsureConfigDir:
    def test_creates_directory(self, tmp_path):
        config_dir = str(tmp_path / "new_config")
        with patch("breadmind.config.get_default_config_dir", return_value=config_dir):
            result = _ensure_config_dir()
        assert result == config_dir
        assert os.path.isdir(config_dir)

    def test_existing_directory_ok(self, tmp_path):
        config_dir = str(tmp_path)
        with patch("breadmind.config.get_default_config_dir", return_value=config_dir):
            result = _ensure_config_dir()
        assert result == config_dir


class TestWriteConfig:
    def test_creates_config_yaml(self, tmp_path):
        config_dir = str(tmp_path)
        _write_config(config_dir, "gemini", "gemini-2.5-flash", None)

        config_path = tmp_path / "config.yaml"
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "default_provider: gemini" in content
        assert "default_model: gemini-2.5-flash" in content
        assert "host:" in content
        assert "port: 8080" in content

    def test_creates_config_with_database(self, tmp_path):
        config_dir = str(tmp_path)
        _write_config(config_dir, "claude", "claude-sonnet-4-6", "postgresql://u:p@h/db")

        content = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "default_provider: claude" in content
        assert "database:" in content
        assert "${DATABASE_URL}" in content

    def test_skip_overwrite_when_declined(self, tmp_path):
        config_dir = str(tmp_path)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("original", encoding="utf-8")

        with patch("builtins.input", return_value="n"):
            _write_config(config_dir, "gemini", "gemini-2.5-flash", None)

        assert config_path.read_text(encoding="utf-8") == "original"

    def test_overwrite_when_confirmed(self, tmp_path):
        config_dir = str(tmp_path)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("original", encoding="utf-8")

        with patch("builtins.input", return_value="y"):
            _write_config(config_dir, "gemini", "gemini-2.5-flash", None)

        content = config_path.read_text(encoding="utf-8")
        assert "default_provider: gemini" in content


class TestWriteEnv:
    def test_writes_api_key(self, tmp_path):
        config_dir = str(tmp_path)
        _write_env(config_dir, "gemini", "test-key-12345", None)

        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=test-key-12345" in content

    def test_writes_db_dsn(self, tmp_path):
        config_dir = str(tmp_path)
        _write_env(config_dir, "gemini", "key123", "postgresql://u:p@h/db")

        content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=key123" in content
        assert "DATABASE_URL=postgresql://u:p@h/db" in content

    def test_no_file_when_no_key_and_no_dsn(self, tmp_path):
        config_dir = str(tmp_path)
        # ollama has no env_key, so no lines to write
        _write_env(config_dir, "ollama", "", None)

        env_path = tmp_path / ".env"
        assert not env_path.exists()


class TestSetupProvider:
    async def test_select_provider_and_enter_key(self):
        """Mock input to select provider 1 (gemini), enter key, default model."""
        inputs = iter(["1", "my-api-key-123", ""])
        with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
            provider_name, api_key, model = await _setup_provider()

        assert provider_name == "gemini"
        assert api_key == "my-api-key-123"
        assert model == "gemini-2.5-flash"

    async def test_select_provider_with_model_choice(self):
        """Select provider 1 and pick model 2."""
        inputs = iter(["1", "key", "2"])
        with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
            provider_name, api_key, model = await _setup_provider()

        assert provider_name == "gemini"
        assert model == "gemini-2.5-pro"

    async def test_invalid_choice_retries(self):
        """Invalid input should re-prompt."""
        inputs = iter(["abc", "0", "99", "1", "key", ""])
        with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
            provider_name, api_key, model = await _setup_provider()

        assert provider_name == "gemini"

    async def test_existing_env_key_reuse(self):
        """When env var exists, user can reuse it."""
        inputs = iter(["2", "y", ""])  # claude, reuse existing key
        with patch("builtins.input", side_effect=lambda prompt="": next(inputs)):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-existing-key-value"}):
                provider_name, api_key, model = await _setup_provider()

        assert provider_name == "claude"
        assert api_key == "sk-existing-key-value"


class TestVerifyApiKey:
    async def test_health_check_success(self):
        mock_provider = MagicMock()
        mock_provider.health_check = AsyncMock(return_value=True)

        mock_info = MagicMock()
        mock_info.cls = MagicMock(return_value=mock_provider)

        with patch("breadmind.llm.factory._PROVIDER_REGISTRY", {"gemini": mock_info}):
            await _verify_api_key("gemini", "test-key", "gemini-2.5-flash")

        mock_info.cls.assert_called_once_with(api_key="test-key", default_model="gemini-2.5-flash")
        mock_provider.health_check.assert_awaited_once()

    async def test_health_check_failure(self):
        mock_provider = MagicMock()
        mock_provider.health_check = AsyncMock(return_value=False)

        mock_info = MagicMock()
        mock_info.cls = MagicMock(return_value=mock_provider)

        with patch("breadmind.llm.factory._PROVIDER_REGISTRY", {"gemini": mock_info}):
            # Should not raise, just print failure
            await _verify_api_key("gemini", "bad-key", "model")

    async def test_health_check_exception(self):
        mock_info = MagicMock()
        mock_info.cls = MagicMock(side_effect=RuntimeError("connection failed"))

        with patch("breadmind.llm.factory._PROVIDER_REGISTRY", {"gemini": mock_info}):
            # Should not raise
            await _verify_api_key("gemini", "key", "model")

    async def test_skip_when_no_key(self):
        with patch("breadmind.llm.factory._PROVIDER_REGISTRY", {"gemini": MagicMock()}):
            await _verify_api_key("gemini", "", "model")

    async def test_skip_unknown_provider(self):
        with patch("breadmind.llm.factory._PROVIDER_REGISTRY", {}):
            await _verify_api_key("unknown", "key", "model")


class TestParseArgs:
    def test_setup_subcommand(self):
        from breadmind.main import _parse_args

        with patch("sys.argv", ["breadmind", "setup"]):
            args = _parse_args()
        assert args.command == "setup"
