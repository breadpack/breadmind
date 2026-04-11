"""Common helper functions used across BreadMind modules."""

from __future__ import annotations

import asyncio
import uuid
from importlib import import_module
from typing import Any


def generate_short_id(length: int = 8) -> str:
    """Generate a short unique ID from UUID4 hex."""
    return uuid.uuid4().hex[:length]


async def cancel_task_safely(task: asyncio.Task | None) -> None:
    """Cancel an asyncio task and suppress CancelledError."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def safe_import(module_path: str, package_display_name: str | None = None) -> Any:
    """Import a module, returning None if not installed."""
    try:
        return import_module(module_path)
    except ImportError:
        return None
