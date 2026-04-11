"""Transparent proxy that lets callers keep a stable reference to an LLM
provider while the underlying instance is swapped out on hot reload."""
from __future__ import annotations

from typing import Any


class LLMProviderHolder:
    """Proxy around a live :class:`LLMProvider` instance.

    Callers can hold the holder and call ``holder.complete(...)`` as if it
    were the provider itself. ``swap(new_provider)`` atomically replaces the
    inner reference — subsequent calls go to the new provider.
    """

    def __init__(self, provider: Any) -> None:
        if provider is None:
            raise ValueError("provider must not be None")
        object.__setattr__(self, "_inner", provider)

    def swap(self, new_provider: Any) -> None:
        if new_provider is None:
            raise ValueError("new_provider must not be None")
        object.__setattr__(self, "_inner", new_provider)

    @property
    def current(self) -> Any:
        return object.__getattribute__(self, "_inner")

    def __getattr__(self, item: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), item)
