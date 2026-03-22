"""Plugin protocol and base class for tool plugins."""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol that all tool plugins must implement."""

    name: str
    version: str

    def get_tools(self) -> list[Callable]:
        """Return list of tool functions to register."""
        ...

    async def setup(self, container: Any) -> None:
        """Initialize plugin with dependencies from the service container."""
        ...

    async def teardown(self) -> None:
        """Cleanup resources when plugin is unloaded."""
        ...


class BaseToolPlugin:
    """Convenience base class for tool plugins.

    Subclasses should set ``name`` and ``version`` as class attributes
    and override ``get_tools()`` and optionally ``setup()`` / ``teardown()``.
    """

    name: str = ""
    version: str = "0.1.0"

    def get_tools(self) -> list[Callable]:
        return []

    async def setup(self, container: Any) -> None:
        pass

    async def teardown(self) -> None:
        pass
