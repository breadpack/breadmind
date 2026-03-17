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
