"""Tests for the coding agent delegation feature."""
from __future__ import annotations

import platform
import sys
import pytest
from unittest.mock import AsyncMock, patch

from breadmind.coding.adapters.base import CodingResult
from breadmind.coding.executors.base import ExecutionResult
from breadmind.coding.adapters.claude_code import ClaudeCodeAdapter
from breadmind.coding.adapters.codex import CodexAdapter
from breadmind.coding.adapters.gemini_cli import GeminiCLIAdapter
from breadmind.coding.adapters import get_adapter
from breadmind.coding.executors.local import LocalExecutor
from breadmind.coding.session_store import CodingSessionStore
from breadmind.coding.project_config import ProjectConfigManager


# ---------------------------------------------------------------------------
# Task 1: Dataclass defaults
# ---------------------------------------------------------------------------

def test_coding_result_defaults():
    result = CodingResult(success=True, output="ok")
    assert result.files_changed == []
    assert result.cost is None
    assert result.execution_time == 0.0
    assert result.agent == ""
    assert result.session_id is None


def test_execution_result_fields():
    result = ExecutionResult(stdout="out", stderr="err", returncode=0)
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Task 2: Adapter build_command
# ---------------------------------------------------------------------------

class TestClaudeCodeAdapter:
    def setup_method(self):
        self.adapter = ClaudeCodeAdapter()

    def test_basic_command(self):
        cmd = self.adapter.build_command("/project", "add tests")
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "add tests" in cmd
        assert "--cwd" in cmd
        assert "/project" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_with_session(self):
        cmd = self.adapter.build_command("/project", "task", {"session_id": "abc123"})
        assert "--resume" in cmd
        assert "abc123" in cmd

    def test_with_model(self):
        cmd = self.adapter.build_command("/project", "task", {"model": "claude-3-5-sonnet"})
        assert "--model" in cmd
        assert "claude-3-5-sonnet" in cmd

    def test_parse_result_success_json(self):
        stdout = '{"result": "done", "session_id": "s1", "files_changed": ["a.py"]}'
        result = self.adapter.parse_result(stdout, "", 0)
        assert result.success is True
        assert result.output == "done"
        assert result.session_id == "s1"
        assert result.files_changed == ["a.py"]

    def test_parse_result_failure(self):
        result = self.adapter.parse_result("", "some error", 1)
        assert result.success is False
        assert "some error" in result.output

    def test_parse_result_malformed_json(self):
        result = self.adapter.parse_result("{not valid json}", "", 0)
        assert result.success is True
        assert "{not valid json}" in result.output


class TestCodexAdapter:
    def setup_method(self):
        self.adapter = CodexAdapter()

    def test_basic_command(self):
        cmd = self.adapter.build_command("/project", "fix bug")
        assert cmd[0] == "codex"
        assert "--prompt" in cmd
        assert "fix bug" in cmd
        assert "--quiet" in cmd

    def test_with_session(self):
        cmd = self.adapter.build_command("/project", "task", {"session_id": "sess42"})
        assert "--session" in cmd
        assert "sess42" in cmd

    def test_no_model_flag(self):
        # Codex adapter does not support model override in the spec
        cmd = self.adapter.build_command("/project", "task", {"model": "gpt-4o"})
        assert "--model" not in cmd

    def test_parse_result_success(self):
        result = self.adapter.parse_result("Task complete.", "", 0)
        assert result.success is True
        assert "Task complete." in result.output

    def test_parse_result_failure(self):
        result = self.adapter.parse_result("", "error occurred", 1)
        assert result.success is False


class TestGeminiCLIAdapter:
    def setup_method(self):
        self.adapter = GeminiCLIAdapter()

    def test_basic_command(self):
        cmd = self.adapter.build_command("/project", "refactor")
        assert cmd[0] == "gemini"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_with_session(self):
        cmd = self.adapter.build_command("/project", "task", {"session_id": "g99"})
        assert "--session" in cmd
        assert "g99" in cmd

    def test_with_model(self):
        cmd = self.adapter.build_command("/project", "task", {"model": "gemini-2.0-flash"})
        assert "--model" in cmd
        assert "gemini-2.0-flash" in cmd

    def test_parse_result_success_json(self):
        stdout = '{"result": "refactored", "session_id": "gsess", "files_changed": ["b.py", "c.py"]}'
        result = self.adapter.parse_result(stdout, "", 0)
        assert result.success is True
        assert result.output == "refactored"
        assert result.session_id == "gsess"
        assert len(result.files_changed) == 2

    def test_parse_result_malformed_json(self):
        result = self.adapter.parse_result("plain text output", "", 0)
        assert result.success is True
        assert "plain text output" in result.output


# ---------------------------------------------------------------------------
# Task 4 (partial): Adapter registry
# ---------------------------------------------------------------------------

def test_get_adapter_valid():
    for name in ("claude", "codex", "gemini"):
        adapter = get_adapter(name)
        assert adapter.name == name


def test_get_adapter_invalid():
    with pytest.raises(ValueError, match="Unknown coding agent"):
        get_adapter("unknown_agent")


# ---------------------------------------------------------------------------
# Task 3: LocalExecutor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_executor_echo():
    executor = LocalExecutor()
    if platform.system() == "Windows":
        cmd = ["cmd", "/c", "echo", "hello"]
    else:
        cmd = ["echo", "hello"]
    result = await executor.run(cmd, cwd=".")
    assert result.returncode == 0
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_local_executor_timeout():
    executor = LocalExecutor()
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "10", "127.0.0.1"]
    else:
        cmd = ["sleep", "10"]
    result = await executor.run(cmd, cwd=".", timeout=1)
    assert result.returncode == -1
    assert "Timeout" in result.stderr


@pytest.mark.asyncio
async def test_local_executor_command_not_found():
    executor = LocalExecutor()
    result = await executor.run(["__nonexistent_cmd_xyz__"], cwd=".")
    assert result.returncode == 127
    assert "not found" in result.stderr.lower() or "Command not found" in result.stderr


# ---------------------------------------------------------------------------
# Task 4: CodingSessionStore (in-memory)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_store_save_and_get():
    store = CodingSessionStore()
    await store.save_session("/myproject", "claude", "sess-001", "Add login feature")
    session_id = await store.get_last_session("/myproject", "claude")
    assert session_id == "sess-001"


@pytest.mark.asyncio
async def test_session_store_get_missing():
    store = CodingSessionStore()
    session_id = await store.get_last_session("/myproject", "codex")
    assert session_id is None


@pytest.mark.asyncio
async def test_session_store_list_sessions():
    store = CodingSessionStore()
    await store.save_session("/proj", "claude", "s1", "task A")
    await store.save_session("/proj", "codex", "s2", "task B")
    await store.save_session("/other", "gemini", "s3", "task C")

    sessions = await store.list_sessions("/proj")
    assert len(sessions) == 2
    agents = {s["agent"] for s in sessions}
    assert "claude" in agents
    assert "codex" in agents


# ---------------------------------------------------------------------------
# Task 4: ProjectConfigManager
# ---------------------------------------------------------------------------

def test_project_config_manager_known_agents():
    mgr = ProjectConfigManager()
    assert mgr.get_config_path("/proj", "claude").name == "CLAUDE.md"
    assert mgr.get_config_path("/proj", "codex").name == "AGENTS.md"
    assert mgr.get_config_path("/proj", "gemini").name == "GEMINI.md"


def test_project_config_manager_unknown_agent():
    mgr = ProjectConfigManager()
    path = mgr.get_config_path("/proj", "myagent")
    assert path.name == "MYAGENT.md"


def test_project_config_manager_ensure_config_missing(tmp_path):
    mgr = ProjectConfigManager()
    result = mgr.ensure_config(str(tmp_path), "claude")
    assert result is None


def test_project_config_manager_ensure_config_exists(tmp_path):
    config_file = tmp_path / "CLAUDE.md"
    config_file.write_text("# Claude config")
    mgr = ProjectConfigManager()
    result = mgr.ensure_config(str(tmp_path), "claude")
    assert result is not None
    assert result.name == "CLAUDE.md"


# ---------------------------------------------------------------------------
# Task 5: code_delegate tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_code_delegate_invalid_agent():
    from breadmind.coding.tool import create_code_delegate_tool
    _, tool_fn = create_code_delegate_tool()
    result = await tool_fn(agent="invalid_agent", project="/tmp", prompt="do something")
    assert result.success is False
    assert "Unknown coding agent" in result.output


@pytest.mark.asyncio
async def test_code_delegate_mocked_success(tmp_path):
    from breadmind.coding.tool import create_code_delegate_tool
    _, tool_fn = create_code_delegate_tool()

    mock_exec_result = ExecutionResult(
        stdout='{"result":"Login feature added","session_id":"s123","files_changed":["auth.py"]}',
        stderr="",
        returncode=0,
    )
    with patch(
        "breadmind.coding.executors.local.LocalExecutor.run",
        new_callable=AsyncMock,
        return_value=mock_exec_result,
    ):
        result = await tool_fn(
            agent="claude",
            project=str(tmp_path),
            prompt="add login",
        )
    assert result.success is True
    assert "s123" in result.output
    assert "auth.py" in result.output


@pytest.mark.asyncio
async def test_code_delegate_missing_local_dir():
    from breadmind.coding.tool import create_code_delegate_tool
    _, tool_fn = create_code_delegate_tool()
    result = await tool_fn(
        agent="claude",
        project="/nonexistent/path/xyz",
        prompt="do something",
    )
    assert result.success is False
    assert "not found" in result.output
