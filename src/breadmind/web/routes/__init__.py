"""Route modules for BreadMind web application."""
from __future__ import annotations

from .chat import setup_chat_routes
from .config import setup_config_routes
from .tools import setup_tools_routes
from .mcp import setup_mcp_routes
from .monitoring import setup_monitoring_routes
from .swarm import setup_swarm_routes
from .system import setup_system_routes

__all__ = [
    "setup_chat_routes",
    "setup_config_routes",
    "setup_tools_routes",
    "setup_mcp_routes",
    "setup_monitoring_routes",
    "setup_swarm_routes",
    "setup_system_routes",
]
