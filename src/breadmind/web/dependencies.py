"""FastAPI dependency injection helpers.

Provides reusable Depends() callables that extract services from the
FastAPI application state.  These functions intentionally do NOT import
any other breadmind module so that they can never introduce circular
imports.

Usage in a route::

    from fastapi import Depends
    from breadmind.web.dependencies import get_config, get_db

    @router.get("/example")
    async def example(config=Depends(get_config), db=Depends(get_db)):
        ...

For testing, use ``app.dependency_overrides``::

    app.dependency_overrides[get_config] = lambda: mock_config
"""
from __future__ import annotations

from fastapi import Request


# ── Core services ─────────────────────────────────────────────────────

def get_app_state(request: Request):
    """Extract the WebApp (app_state) instance from the FastAPI app."""
    return request.app.state.app_state


def get_db(request: Request):
    """Get database instance."""
    return request.app.state.app_state._db


def get_config(request: Request):
    """Get config instance."""
    return request.app.state.app_state._config


def get_agent(request: Request):
    """Get agent instance."""
    return request.app.state.app_state._agent


def get_guard(request: Request):
    """Get safety guard instance."""
    return request.app.state.app_state._safety_guard


# ── Domain services ───────────────────────────────────────────────────

def get_scheduler(request: Request):
    """Get scheduler instance."""
    return request.app.state.app_state._scheduler


def get_subagent_manager(request: Request):
    """Get sub-agent manager instance."""
    return request.app.state.app_state._subagent_manager


def get_container_executor(request: Request):
    """Get container executor instance."""
    return request.app.state.app_state._container_executor


def get_safety_config(request: Request):
    """Get safety config dict."""
    return request.app.state.app_state._safety_config


def get_search_engine(request: Request):
    """Get registry search engine instance."""
    return request.app.state.app_state._search_engine


def get_mcp_manager(request: Request):
    """Get MCP manager instance."""
    return request.app.state.app_state._mcp_manager


def get_mcp_store(request: Request):
    """Get MCP store instance."""
    return request.app.state.app_state._mcp_store


def get_tool_registry(request: Request):
    """Get tool registry instance."""
    return request.app.state.app_state._tool_registry


def get_monitoring_engine(request: Request):
    """Get monitoring engine instance."""
    return request.app.state.app_state._monitoring_engine


def get_audit_logger(request: Request):
    """Get audit logger instance."""
    return request.app.state.app_state._audit_logger


def get_metrics_collector(request: Request):
    """Get metrics collector instance."""
    return request.app.state.app_state._metrics_collector


def get_swarm_manager(request: Request):
    """Get swarm manager instance."""
    return request.app.state.app_state._swarm_manager


def get_skill_store(request: Request):
    """Get skill store instance."""
    return request.app.state.app_state._skill_store


def get_performance_tracker(request: Request):
    """Get performance tracker instance."""
    return request.app.state.app_state._performance_tracker


def get_working_memory(request: Request):
    """Get working memory instance."""
    return request.app.state.app_state._working_memory


def get_message_router(request: Request):
    """Get message router instance."""
    return request.app.state.app_state._message_router


def get_webhook_manager(request: Request):
    """Get webhook manager instance."""
    return request.app.state.app_state._webhook_manager


def get_auth(request: Request):
    """Get auth manager instance."""
    return request.app.state.app_state._auth


def get_message_handler(request: Request):
    """Get message handler callable."""
    return request.app.state.app_state._message_handler


def get_events(request: Request):
    """Get events list."""
    return request.app.state.app_state._events


def get_token_manager(request: Request):
    """Get token manager instance."""
    return getattr(request.app.state.app_state, '_token_manager', None)


def get_commander(request: Request):
    """Get commander instance."""
    return getattr(request.app.state.app_state, '_commander', None)


def get_credential_vault(request: Request):
    """Get credential vault instance."""
    return getattr(request.app.state, 'credential_vault', None)


def get_webhook_automation_store(request: Request):
    """Get webhook automation store instance."""
    return getattr(request.app.state.app_state, '_webhook_automation_store', None)
