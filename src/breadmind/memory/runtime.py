"""Runtime helpers for org_id resolution and Slack team lookup.

The lookup cache uses a process-local dict + asyncio.Lock (NOT lru_cache,
which is incompatible with async functions — caching a coroutine causes
RuntimeError on the second call).

**Loop binding** — ``_cache_lock`` is constructed at module import. Python
3.10+ lazy-binds ``asyncio.Lock`` to the running loop on first ``await``, so
pytest-asyncio's per-test loop pattern works. A long-running process that
re-creates its event loop (e.g. multiple ``asyncio.run`` calls) would fail
with ``RuntimeError: <Lock> is bound to a different loop`` — single-loop
deployments only.

**Cache invalidation** — ``clear_org_lookup_cache()`` clears only the dict,
not the lock. The lock is intentionally not reset; resetting a held lock
would race with concurrent lookups. Cache invalidation and loop binding
are orthogonal concerns.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)

# Sentinel marking "caller did not supply env_default" — distinguishes from
# the legitimate value ``None``. Module-private object identity check.
_UNSET: Final[object] = object()


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    """Accept a UUID or its canonical string form; return None for invalid input."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _parse_env_uuid(env_var: str) -> uuid.UUID | None:
    """Parse a UUID from an env var; warn and return None on invalid format."""
    raw = os.environ.get(env_var)
    if not raw:
        return None
    parsed = _coerce_uuid(raw)
    if parsed is None:
        logger.warning("Invalid UUID in env %s=%r; treating as unset", env_var, raw)
    return parsed


def _resolve_org_id(
    explicit: uuid.UUID | None = None,
    ctx_org_id: uuid.UUID | None = None,
    env_default: uuid.UUID | None = _UNSET,  # type: ignore[assignment]
) -> uuid.UUID | None:
    """Resolve org_id by 4-step fallback: explicit → ctx → env → None.

    When ``env_default`` is omitted, BREADMIND_DEFAULT_ORG_ID is read at
    call time. Pass an explicit value (including ``None``) to override.
    Callers that pass a ``str`` must pre-coerce via ``_coerce_uuid``.
    """
    if env_default is _UNSET:
        env_default = _parse_env_uuid("BREADMIND_DEFAULT_ORG_ID")
    return _coerce_uuid(explicit) or _coerce_uuid(ctx_org_id) or env_default or None


# --- Slack team → org_id cache (async-safe) ---

_team_to_org_cache: dict[str, uuid.UUID | None] = {}
_cache_lock = asyncio.Lock()


async def _lookup_org_id_by_slack_team(team_id: str, db: "Database") -> uuid.UUID | None:
    """Resolve a Slack team_id to org_projects.id; cache hits and misses."""
    if team_id in _team_to_org_cache:
        return _team_to_org_cache[team_id]
    async with _cache_lock:
        if team_id in _team_to_org_cache:
            return _team_to_org_cache[team_id]
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM org_projects WHERE slack_team_id = $1",
                team_id,
            )
        org_id = row["id"] if row else None
        # TODO(T8): emit breadmind_org_id_lookup_total{outcome="hit"|"miss"}
        # + 1-time WARN log on miss per spec R2 (call-site, Slack router).
        _team_to_org_cache[team_id] = org_id
        return org_id


def clear_org_lookup_cache() -> None:
    """Test/operator hook to invalidate the in-memory mapping cache.

    The lock is intentionally NOT reset — clearing a held lock would race
    with concurrent lookups.
    """
    _team_to_org_cache.clear()
