"""Base framework for KB connectors (ingest external sources into the pipeline).

Every connector:
  * has a stable ``connector_name`` (ClassVar) used as the ``connector`` key
    in the ``connector_sync_state`` table;
  * implements ``_do_sync(project_id, scope_key, cursor) -> SyncResult`` where
    ``cursor`` is the persisted checkpoint (e.g. a Confluence ``lastModified``
    timestamp, a Jira updated-since, a Google Drive pageToken);
  * is invoked through :meth:`BaseConnector.sync`, which handles cursor
    persistence and error accounting uniformly.

On success ``last_cursor`` is advanced to ``result.new_cursor``; on failure the
cursor is preserved verbatim so the next run retries the same window, and the
original exception is re-raised after the error row is written.
"""
from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Protocol

__all__ = ["BaseConnector", "SyncResult"]


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a single connector sync pass.

    Attributes:
        new_cursor: Opaque checkpoint string to persist for the next run.
            For time-based connectors this is typically an ISO-8601 UTC
            timestamp; for token-based APIs it is the provider's page token.
        processed: Number of source items consumed during this pass
            (regardless of whether they produced candidates).
        errors: Per-item errors swallowed during processing. A fully failed
            sync raises rather than returning ``errors > 0``.
    """

    new_cursor: str
    processed: int
    errors: int


class _DBLike(Protocol):
    async def fetchrow(self, sql: str, *args: Any) -> Any: ...
    async def execute(self, sql: str, *args: Any) -> Any: ...


_SELECT_STATE_SQL = """
    SELECT connector, scope_key, project_id, last_cursor,
           last_run_at, last_status, last_error
      FROM connector_sync_state
     WHERE connector = $1 AND scope_key = $2
"""

_UPSERT_STATE_SQL = """
    INSERT INTO connector_sync_state
        (connector, scope_key, project_id, last_cursor,
         last_run_at, last_status, last_error)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (connector, scope_key) DO UPDATE SET
        project_id  = EXCLUDED.project_id,
        last_cursor = EXCLUDED.last_cursor,
        last_run_at = EXCLUDED.last_run_at,
        last_status = EXCLUDED.last_status,
        last_error  = EXCLUDED.last_error
"""


class BaseConnector(abc.ABC):
    """Abstract base for KB connectors.

    Subclasses must set ``connector_name`` and implement :meth:`_do_sync`.
    Instantiating a subclass that does not set ``connector_name`` raises
    ``TypeError`` — the value is used as a DB key, so leaving it unset would
    silently collide state across connectors.
    """

    connector_name: ClassVar[str] = ""

    def __init__(self, db: _DBLike) -> None:
        if not self.connector_name:
            raise TypeError(
                f"{type(self).__name__} must set a non-empty "
                "ClassVar 'connector_name'"
            )
        self._db = db

    # ------------------------------------------------------------------ state

    async def load_cursor(self, scope_key: str) -> str | None:
        """Return the persisted cursor for ``scope_key`` or ``None`` if absent."""
        row = await self._db.fetchrow(
            _SELECT_STATE_SQL, self.connector_name, scope_key
        )
        if row is None:
            return None
        return row["last_cursor"]

    async def _persist_state(
        self,
        *,
        project_id: uuid.UUID,
        scope_key: str,
        cursor: str | None,
        status: str,
        error: str | None,
    ) -> None:
        await self._db.execute(
            _UPSERT_STATE_SQL,
            self.connector_name,
            scope_key,
            project_id,
            cursor,
            datetime.now(timezone.utc),
            status,
            error,
        )

    # ------------------------------------------------------------------- sync

    @abc.abstractmethod
    async def _do_sync(
        self,
        project_id: uuid.UUID,
        scope_key: str,
        cursor: str | None,
    ) -> SyncResult:
        """Perform one sync pass and return the new cursor + counters.

        Implementations must be side-effect-safe to retry: on failure the
        framework preserves the previous cursor, so the same window will be
        reprocessed.
        """

    async def sync(
        self,
        project_id: uuid.UUID,
        scope_key: str,
        *,
        cursor: str | None = None,
    ) -> SyncResult:
        """Run a sync pass, persisting cursor + status regardless of outcome.

        On success: writes ``last_status='ok'`` and advances ``last_cursor``
        to ``result.new_cursor``.
        On failure: writes ``last_status='error'`` with the exception text
        in ``last_error`` and leaves ``last_cursor`` unchanged, then re-raises.
        """
        try:
            result = await self._do_sync(project_id, scope_key, cursor)
        except Exception as exc:
            await self._persist_state(
                project_id=project_id,
                scope_key=scope_key,
                cursor=cursor,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        await self._persist_state(
            project_id=project_id,
            scope_key=scope_key,
            cursor=result.new_cursor,
            status="ok",
            error=None,
        )
        return result
