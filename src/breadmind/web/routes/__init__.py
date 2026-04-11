"""Route modules for BreadMind web application."""
from __future__ import annotations

from .chat import setup_chat_routes
from .config import setup_config_routes
from .containers import setup_container_routes
from .tools import setup_tools_routes
from .mcp import setup_mcp_routes
from .monitoring import setup_monitoring_routes
from .scheduler import setup_scheduler_routes
from .subagent import setup_subagent_routes
from .swarm import setup_swarm_routes
from .system import setup_system_routes
from .browser import setup_browser_routes

__all__ = [
    "setup_browser_routes",
    "setup_chat_routes",
    "setup_config_routes",
    "setup_container_routes",
    "setup_tools_routes",
    "setup_mcp_routes",
    "setup_monitoring_routes",
    "setup_scheduler_routes",
    "setup_subagent_routes",
    "setup_swarm_routes",
    "setup_system_routes",
]
