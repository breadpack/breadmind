"""Personal CLI command tests."""
import argparse
from unittest.mock import AsyncMock

import pytest

from breadmind.personal.adapters.base import AdapterRegistry


@pytest.fixture
def mock_registry():
    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    task_adapter.create_item = AsyncMock(return_value="new-id-12345678")
    task_adapter.update_item = AsyncMock(return_value=True)
    task_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    event_adapter.create_item = AsyncMock(return_value="new-event-id")
    event_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(event_adapter)

    return registry


def test_register_commands():
    from breadmind.cli.personal import register_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    register_commands(sub)
    # Should not raise
    args = parser.parse_args(["task", "list"])
    assert args.command == "task"
    assert args.task_action == "list"


def test_register_task_add():
    from breadmind.cli.personal import register_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    register_commands(sub)
    args = parser.parse_args(["task", "add", "Buy milk", "--priority", "high"])
    assert args.title == "Buy milk"
    assert args.priority == "high"


def test_register_event_add():
    from breadmind.cli.personal import register_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    register_commands(sub)
    args = parser.parse_args([
        "event", "add", "Meeting", "--start", "2026-03-18T09:00",
        "--end", "2026-03-18T10:00", "--location", "Room A",
    ])
    assert args.title == "Meeting"
    assert args.start == "2026-03-18T09:00"
    assert args.location == "Room A"


def test_register_contact_add():
    from breadmind.cli.personal import register_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    register_commands(sub)
    args = parser.parse_args([
        "contact", "add", "Alice", "--email", "a@b.com", "--phone", "010-1234",
    ])
    assert args.name == "Alice"
    assert args.email == "a@b.com"


def test_register_remind():
    from breadmind.cli.personal import register_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    register_commands(sub)
    args = parser.parse_args([
        "remind", "Take medicine", "--at", "2026-03-18T18:00",
        "--recurrence", "daily",
    ])
    assert args.message == "Take medicine"
    assert args.recurrence == "daily"


@pytest.mark.asyncio
async def test_handle_task_list(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="task", task_action="list", status="pending", priority=None,
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "없습니다" in captured.out


@pytest.mark.asyncio
async def test_handle_task_add(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="task", task_action="add",
        title="Test", due=None, priority="medium", tags=None,
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "추가" in captured.out


@pytest.mark.asyncio
async def test_handle_task_done(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="task", task_action="done", task_id="abc12345-full-id",
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "완료" in captured.out
    mock_registry.get_adapter("task", "builtin").update_item.assert_called_once()


@pytest.mark.asyncio
async def test_handle_task_delete(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="task", task_action="delete", task_id="abc12345-full-id",
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "삭제" in captured.out


@pytest.mark.asyncio
async def test_handle_event_list(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="event", event_action="list", days=7,
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "없습니다" in captured.out


@pytest.mark.asyncio
async def test_handle_event_add(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="event", event_action="add",
        title="Team meeting", start="2026-03-18T09:00",
        end="2026-03-18T10:00", location="Room A",
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "추가" in captured.out


@pytest.mark.asyncio
async def test_handle_event_delete(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="event", event_action="delete", event_id="evt-12345678",
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "삭제" in captured.out


@pytest.mark.asyncio
async def test_handle_remind(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(
        command="remind", message="Take medicine",
        at="2026-03-18T18:00:00Z", recurrence=None,
    )
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "리마인더" in captured.out


@pytest.mark.asyncio
async def test_handle_unknown_command(mock_registry, capsys):
    from breadmind.cli.personal import handle_command

    args = argparse.Namespace(command="unknown")
    await handle_command(args, mock_registry)
    captured = capsys.readouterr()
    assert "Unknown command" in captured.out
