"""Tests for breadmind chat CLI command."""
from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, patch



# ── Argument parsing ─────────────────────────────────────────────────

def _parse_chat_args(argv: list[str]) -> argparse.Namespace:
    """main.py의 _parse_args를 직접 호출하지 않고 chat 서브커맨드 파서만 테스트."""
    from breadmind.main import _parse_args

    # Monkey-patch sys.argv
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["breadmind"] + argv
        return _parse_args()
    finally:
        sys.argv = old_argv


class TestChatArgParsing:
    def test_chat_default(self):
        args = _parse_chat_args(["chat"])
        assert args.command == "chat"
        assert args.model is None
        assert args.stream is True
        assert args.no_stream is False
        assert args.continue_session is None
        assert args.config_dir is None
        assert args.log_level is None

    def test_chat_model_override(self):
        args = _parse_chat_args(["chat", "--model", "claude-haiku-4-5"])
        assert args.model == "claude-haiku-4-5"

    def test_chat_no_stream(self):
        args = _parse_chat_args(["chat", "--no-stream"])
        assert args.no_stream is True

    def test_chat_continue_session(self):
        args = _parse_chat_args(["chat", "--continue", "session123"])
        assert args.continue_session == "session123"

    def test_chat_config_dir(self):
        args = _parse_chat_args(["chat", "--config-dir", "/tmp/myconfig"])
        assert args.config_dir == "/tmp/myconfig"

    def test_chat_log_level(self):
        args = _parse_chat_args(["chat", "--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_chat_combined_args(self):
        args = _parse_chat_args([
            "chat", "--model", "gpt-4", "--no-stream",
            "--continue", "abc123", "--log-level", "ERROR",
        ])
        assert args.model == "gpt-4"
        assert args.no_stream is True
        assert args.continue_session == "abc123"
        assert args.log_level == "ERROR"


# ── _register_basic_tools ────────────────────────────────────────────

class TestRegisterBasicTools:
    def test_registers_three_tools(self):
        from breadmind.cli.chat import _register_basic_tools
        from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

        registry = HybridToolRegistry()
        _register_basic_tools(registry)

        tool_names = set(registry._tools.keys())
        assert "shell_exec" in tool_names
        assert "file_read" in tool_names
        assert "file_write" in tool_names

    def test_executors_registered(self):
        from breadmind.cli.chat import _register_basic_tools
        from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

        registry = HybridToolRegistry()
        _register_basic_tools(registry)

        assert callable(registry._executors["shell_exec"])
        assert callable(registry._executors["file_read"])
        assert callable(registry._executors["file_write"])

    async def test_file_read_executor(self, tmp_path):
        from breadmind.cli.chat import _register_basic_tools
        from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

        registry = HybridToolRegistry()
        _register_basic_tools(registry)

        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world", encoding="utf-8")

        result = await registry._executors["file_read"](path=str(test_file))
        assert result == "hello world"

    async def test_file_write_executor(self, tmp_path):
        from breadmind.cli.chat import _register_basic_tools
        from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

        registry = HybridToolRegistry()
        _register_basic_tools(registry)

        out_file = tmp_path / "out.txt"
        result = await registry._executors["file_write"](
            path=str(out_file), content="test content",
        )
        assert "12 chars" in result
        assert out_file.read_text(encoding="utf-8") == "test content"

    async def test_shell_exec_executor(self):
        from breadmind.cli.chat import _register_basic_tools
        from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

        registry = HybridToolRegistry()
        _register_basic_tools(registry)

        import sys
        cmd = f'{sys.executable} -c "print(42)"'
        result = await registry._executors["shell_exec"](command=cmd)
        assert "42" in result


# ── _create_prompt_builder ───────────────────────────────────────────

class TestPromptBuilder:
    def test_builds_identity_block(self):
        from breadmind.cli.chat import _create_prompt_builder
        from breadmind.core.protocols import PromptContext

        builder = _create_prompt_builder()
        ctx = PromptContext(persona_name="TestBot", language="en")
        blocks = builder.build(ctx)

        assert len(blocks) >= 1
        identity = blocks[0]
        assert identity.section == "identity"
        assert "TestBot" in identity.content
        assert "en" in identity.content

    def test_includes_role_block(self):
        from breadmind.cli.chat import _create_prompt_builder
        from breadmind.core.protocols import PromptContext

        builder = _create_prompt_builder()
        ctx = PromptContext(persona_name="X", language="ko", role="k8s_expert")
        blocks = builder.build(ctx)

        role_blocks = [b for b in blocks if b.section == "role"]
        assert len(role_blocks) == 1
        assert "k8s_expert" in role_blocks[0].content

    def test_no_role_block_when_none(self):
        from breadmind.cli.chat import _create_prompt_builder
        from breadmind.core.protocols import PromptContext

        builder = _create_prompt_builder()
        ctx = PromptContext(persona_name="X", language="ko")
        blocks = builder.build(ctx)

        role_blocks = [b for b in blocks if b.section == "role"]
        assert len(role_blocks) == 0

    def test_includes_custom_instructions(self):
        from breadmind.cli.chat import _create_prompt_builder
        from breadmind.core.protocols import PromptContext

        builder = _create_prompt_builder()
        ctx = PromptContext(persona_name="X", language="ko", custom_instructions="Be extra careful")
        blocks = builder.build(ctx)

        custom_blocks = [b for b in blocks if b.section == "custom"]
        assert len(custom_blocks) == 1
        assert "Be extra careful" in custom_blocks[0].content


# ── Fallback config ──────────────────────────────────────────────────

class TestFallbackConfig:
    def test_fallback_config_structure(self):
        from breadmind.cli.chat import _make_fallback_config

        config = _make_fallback_config()
        assert config.llm.default_provider == "ollama"
        assert config.llm.default_model is None
        config.validate()  # should not raise


# ── run_chat routing in main.run() ───────────────────────────────────

class TestChatRouting:
    async def test_chat_command_routes_to_run_chat(self):
        """run() 함수에서 chat 명령이 run_chat로 라우팅되는지 확인."""
        mock_run_chat = AsyncMock()

        with patch("breadmind.main._parse_args") as mock_parse, \
             patch("breadmind.cli.chat.run_chat", mock_run_chat):
            mock_args = argparse.Namespace(command="chat")
            mock_parse.return_value = mock_args

            from breadmind.main import run
            await run()

            mock_run_chat.assert_called_once_with(mock_args)
