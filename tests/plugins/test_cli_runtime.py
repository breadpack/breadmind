import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.plugins.v2_builtin.runtimes.cli_runtime import CLIRuntime
from breadmind.core.protocols import UserInput, AgentOutput, Progress


def test_cli_runtime_creation():
    agent = MagicMock()
    agent.name = "TestBot"
    rt = CLIRuntime(agent=agent)
    assert rt._agent.name == "TestBot"
    assert rt._prompt == "> "


@pytest.mark.asyncio
async def test_send_prints_output(capsys):
    agent = MagicMock()
    agent.name = "TestBot"
    rt = CLIRuntime(agent=agent)
    await rt.send(AgentOutput(text="Hello from agent"))
    captured = capsys.readouterr()
    assert "Hello from agent" in captured.out


@pytest.mark.asyncio
async def test_send_progress(capsys):
    agent = MagicMock()
    agent.name = "TestBot"
    rt = CLIRuntime(agent=agent)
    await rt.send_progress(Progress(status="thinking"))
    captured = capsys.readouterr()
    assert "Thinking" in captured.out


@pytest.mark.asyncio
async def test_stop():
    agent = MagicMock()
    agent.name = "TestBot"
    rt = CLIRuntime(agent=agent)
    rt._running = True
    await rt.stop()
    assert rt._running is False
