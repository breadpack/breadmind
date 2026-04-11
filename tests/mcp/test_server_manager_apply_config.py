"""Tests for MCPServerManager.apply_config hot-reload reconciliation."""
from __future__ import annotations

from unittest.mock import AsyncMock

from breadmind.core.events import EventBus
from breadmind.mcp.server_manager import (
    MCPServerConfig,
    MCPServerManager,
    MCPServerState,
)


def _make_manager() -> MCPServerManager:
    mgr = MCPServerManager(event_bus=EventBus())
    mgr.add_server = AsyncMock()
    mgr.remove_server = AsyncMock()
    mgr.restart_server = AsyncMock()
    return mgr


async def test_apply_config_adds_new_servers():
    mgr = _make_manager()
    await mgr.apply_config(
        servers=[
            {
                "name": "github",
                "command": "npx",
                "args": ["-y", "gh"],
                "env": {},
                "enabled": True,
            },
            {
                "name": "local",
                "command": "python",
                "args": ["-m", "l"],
                "env": {},
                "enabled": True,
            },
        ]
    )
    added = [c.args[0].name for c in mgr.add_server.call_args_list]
    assert set(added) == {"github", "local"}
    mgr.remove_server.assert_not_called()
    mgr.restart_server.assert_not_called()


async def test_apply_config_removes_disappeared_servers():
    mgr = _make_manager()
    stale_config = MCPServerConfig(
        name="stale", command="npx", args=[], env={}, enabled=True
    )
    mgr._servers["stale"] = MCPServerState(config=stale_config)

    await mgr.apply_config(
        servers=[
            {
                "name": "github",
                "command": "npx",
                "args": [],
                "env": {},
                "enabled": True,
            },
        ]
    )

    mgr.remove_server.assert_awaited_once_with("stale")
    added = [c.args[0].name for c in mgr.add_server.call_args_list]
    assert added == ["github"]


async def test_apply_config_restarts_changed_enabled_servers():
    mgr = _make_manager()
    existing_cfg = MCPServerConfig(
        name="github", command="npx", args=["-y", "gh"], env={}, enabled=True
    )
    mgr._servers["github"] = MCPServerState(config=existing_cfg)

    await mgr.apply_config(
        servers=[
            {
                "name": "github",
                "command": "uvx",
                "args": ["gh"],
                "env": {},
                "enabled": True,
            },
        ]
    )

    mgr.restart_server.assert_awaited_once_with("github")
    mgr.add_server.assert_not_called()
    mgr.remove_server.assert_not_called()


async def test_apply_config_disabled_server_is_removed():
    mgr = _make_manager()
    mgr._servers["github"] = MCPServerState(
        config=MCPServerConfig(
            name="github", command="npx", args=[], env={}, enabled=True
        )
    )

    await mgr.apply_config(
        servers=[
            {
                "name": "github",
                "command": "npx",
                "args": [],
                "env": {},
                "enabled": False,
            },
        ]
    )

    mgr.remove_server.assert_awaited_once_with("github")
    mgr.add_server.assert_not_called()
    mgr.restart_server.assert_not_called()


async def test_apply_config_global_config_stores_value():
    mgr = _make_manager()
    await mgr.apply_config(mcp_cfg={"auto_discover": True})
    assert mgr._global_config == {"auto_discover": True}
