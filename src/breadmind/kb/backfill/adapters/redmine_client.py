"""RedmineClient — thin async REST client for on-prem Redmine instances.

Isolates all on-prem variability:
  - auth_mode: "api_key" (X-Redmine-API-Key) or "basic" (HTTP Basic)
  - verify_ssl: TLS verification (False triggers audit log)
  - rate_limit_qps: self-imposed QPS ceiling (default 2.0)
  - closed_status_ids: fallback for pre-4.x instances lacking is_closed

All public methods are async and yield / return typed dataclasses from
``redmine_types``. No adapter logic lives here.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import aiohttp

from breadmind.kb.backfill.adapters.redmine_parsers import (
    parse_dt as _parse_dt,
    parse_issue as _parse_issue,
    parse_user_ref as _parse_user_ref,
)
from breadmind.kb.backfill.adapters.redmine_types import (
    RedmineAttachment,
    RedmineIssue,
    RedmineMembership,
    RedmineWikiPage,
)

logger = logging.getLogger(__name__)

# Shared backoff ladder — same tuple as slack._BACKOFF_SECONDS and
# ConfluenceConnector._BACKOFF_SECONDS so on-prem rate signals behave
# identically across connectors.
_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800)

# Eligible MIME prefixes + full types for attachment Phase-1 policy.
_ATTACHMENT_MIME_PREFIXES = ("text/",)
_ATTACHMENT_MIME_EXACT = {
    "application/json",
    "application/xml",
    "application/x-yaml",
}
_ATTACHMENT_MAX_BYTES = 1_048_576  # 1 MiB


class RedmineAuthError(Exception):
    """Raised when the Redmine API returns 401/403 on identity endpoints."""


class RedmineClient:
    """Async REST client for an on-prem Redmine instance.

    All on-prem knobs are injected at construction; they must not bleed into
    the adapter layer.

    Args:
        base_url: HTTPS base URL of the Redmine instance.
        api_key: API key for ``auth_mode="api_key"``.
        auth_mode: ``"api_key"`` (default) or ``"basic"``.
        basic_user: Username for basic auth (ignored for api_key mode).
        basic_password: Password for basic auth.
        verify_ssl: Enable TLS certificate verification (default ``True``).
        rate_limit_qps: Self-imposed QPS ceiling (default ``2.0``).
        closed_status_ids: Fallback closed-status ids for pre-4.x instances.
        audit_log: Callable ``(msg: str) -> None`` for security-relevant events.
        _session: Injected ``aiohttp.ClientSession`` (for tests only).
        _clock: Callable returning monotonic time (for tests only).
        _sleep: Async callable replacing ``asyncio.sleep`` (for tests only).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        auth_mode: str = "api_key",
        basic_user: str | None = None,
        basic_password: str | None = None,
        verify_ssl: bool = True,
        rate_limit_qps: float = 2.0,
        closed_status_ids: list[int] | None = None,
        audit_log=None,
        _session=None,
        _clock=None,
        _sleep=None,
    ) -> None:
        if not base_url:
            raise ValueError("RedmineClient: base_url is required")
        if not base_url.startswith("https://"):
            raise ValueError(
                f"RedmineClient: base_url must start with 'https://', got {base_url!r}"
            )
        if auth_mode == "api_key" and not api_key:
            raise ValueError(
                "RedmineClient: api_key required when auth_mode='api_key'"
            )
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._auth_mode = auth_mode
        self._basic_user = basic_user
        self._basic_password = basic_password
        self.verify_ssl = verify_ssl
        self.rate_limit_qps = rate_limit_qps
        self.closed_status_ids: frozenset[int] = frozenset(closed_status_ids or [])
        self._audit_log = audit_log
        self._external_session = _session
        self._clock = _clock or (lambda: asyncio.get_event_loop().time())
        self._sleep = _sleep or asyncio.sleep
        # Rate-limit state: semaphore + last-request timestamp.
        self._sem = asyncio.Semaphore(1)
        self._last_request_at: float = 0.0
        # One-shot warning flag for is_closed fallback.
        self._warned_is_closed_fallback = False
        # Audit log for verify_ssl=False emitted only once.
        self._ssl_audit_emitted = False

    @classmethod
    def from_vault(cls, vault: dict[str, Any], ref: str, **kw) -> "RedmineClient":
        """Construct from a credential vault dict under ``ref``.

        Expected JSON shape::

            {
                "base_url": "https://redmine.acme.internal/",
                "api_key": "abc123",          # required for api_key mode
                "auth_mode": "api_key",       # or "basic"
                "verify_ssl": true,
                "rate_limit_qps": 2.0,
                "closed_status_ids": []
            }
        """
        creds = vault.get(ref) or {}
        if not creds:
            raise KeyError(f"RedmineClient: vault ref {ref!r} not found")
        return cls(
            base_url=creds.get("base_url", ""),
            api_key=creds.get("api_key"),
            auth_mode=creds.get("auth_mode", "api_key"),
            basic_user=creds.get("basic_user"),
            basic_password=creds.get("basic_password"),
            verify_ssl=bool(creds.get("verify_ssl", True)),
            rate_limit_qps=float(creds.get("rate_limit_qps", 2.0)),
            closed_status_ids=creds.get("closed_status_ids") or [],
            **kw,
        )

    def _build_auth_header(self) -> dict[str, str]:
        if self._auth_mode == "api_key":
            return {"X-Redmine-API-Key": self._api_key or ""}
        # basic
        credentials = f"{self._basic_user or ''}:{self._basic_password or ''}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _instance_id(self) -> str:
        return hashlib.sha256(self.base_url.encode()).hexdigest()[:16]

    def _emit_ssl_audit(self) -> None:
        if not self._ssl_audit_emitted:
            self._ssl_audit_emitted = True
            msg = (
                f"RedmineClient: verify_ssl=False for {self.base_url} — "
                "TLS certificate validation is DISABLED; "
                "ensure this is an approved on-prem instance."
            )
            logger.warning(msg)
            if self._audit_log is not None:
                self._audit_log(msg)

    async def _get_json(self, path: str, params: dict | None = None) -> Any:
        """Perform a GET with rate-limit pacing, retry, and TLS audit."""
        url = f"{self.base_url}{path}"
        headers = self._build_auth_header()
        backoffs = list(_BACKOFF_SECONDS)
        max_attempts = len(_BACKOFF_SECONDS) + 1
        for attempt in range(max_attempts):
            # Emit ssl audit on first request when verify_ssl=False.
            if not self.verify_ssl:
                self._emit_ssl_audit()
            async with self._sem:
                # QPS pacing: enforce 1/rate_limit_qps gap between requests.
                now = self._clock()
                gap = 1.0 / self.rate_limit_qps
                wait = self._last_request_at + gap - now
                if wait > 0:
                    await self._sleep(wait)
                self._last_request_at = self._clock()
                async with self._make_session() as session:
                    async with session.get(
                        url,
                        headers=headers,
                        params=params or {},
                        ssl=False if not self.verify_ssl else None,
                    ) as resp:
                        if resp.status == 401:
                            raise RedmineAuthError(
                                f"Redmine returned 401 for {url}"
                            )
                        if resp.status == 403:
                            raise PermissionError(
                                f"Redmine returned 403 for {url}"
                            )
                        if resp.status == 429:
                            retry_after_hdr = resp.headers.get("Retry-After")
                            if attempt == max_attempts - 1:
                                raise RuntimeError(
                                    f"Redmine 429 after {max_attempts} attempts for {url}"
                                )
                            wait_s: float
                            if retry_after_hdr:
                                wait_s = float(retry_after_hdr)
                            else:
                                wait_s = float(
                                    backoffs.pop(0) if backoffs
                                    else _BACKOFF_SECONDS[-1]
                                )
                            await self._sleep(wait_s)
                            continue
                        if resp.status >= 500:
                            if attempt == max_attempts - 1:
                                raise RuntimeError(
                                    f"Redmine {resp.status} after {max_attempts} attempts for {url}"
                                )
                            wait_s = float(
                                backoffs.pop(0) if backoffs
                                else _BACKOFF_SECONDS[-1]
                            )
                            await self._sleep(wait_s)
                            continue
                        return await resp.json(content_type=None)
        raise RuntimeError(
            f"Redmine unreachable after {max_attempts} attempts for {url}"
        )

    def _make_session(self):
        """Return an aiohttp ClientSession (or the injected test session)."""
        if self._external_session is not None:
            return _NullContextSession(self._external_session)
        return aiohttp.ClientSession()

    async def verify_identity(self) -> int:
        """Call ``GET /users/current.json`` and return the resolved user id.

        Raises ``RedmineAuthError`` on 401.
        """
        data = await self._get_json("/users/current.json")
        user = data.get("user") or {}
        return int(user["id"])

    async def fetch_memberships(self, project_id: int | str) -> list[RedmineMembership]:
        """Return all project memberships for ``project_id``.

        Falls back to a per-user endpoint only when the project endpoint
        returns 403, consistent with spec §Permission Lock step 2.
        """
        try:
            data = await self._get_json(
                f"/projects/{project_id}/memberships.json",
                params={"limit": 100},
            )
        except PermissionError:
            # Fallback: caller may retry via user-level endpoint if needed;
            # here we re-raise so the adapter can decide (spec step 2).
            raise
        memberships: list[RedmineMembership] = []
        for m in data.get("memberships") or []:
            user_raw = m.get("user") or {}
            user_id = user_raw.get("id")
            if user_id is None:
                continue  # group memberships — skip in Phase 1
            project_raw = m.get("project") or {}
            pid = project_raw.get("id") or project_id
            roles = [r.get("name", "") for r in (m.get("roles") or [])]
            memberships.append(
                RedmineMembership(
                    project_id=int(pid),
                    user_id=int(user_id),
                    role_names=roles,
                )
            )
        return memberships

    async def iter_issues(
        self,
        project_id: int | str,
        since: datetime,
        until: datetime,
    ) -> AsyncIterator[RedmineIssue]:
        """Yield issues in the ``[since, until]`` window using keyset pagination.

        Uses ``updated_on`` server-side filter + ``(updated_on, id)`` keyset
        de-duplication to handle page-boundary shifts (spec §Pagination).
        """
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        offset = 0
        limit = 100
        last_updated_on: datetime | None = None
        last_id: int = 0

        while True:
            params = {
                "project_id": str(project_id),
                "status_id": "*",
                "sort": "updated_on:asc",
                "limit": str(limit),
                "offset": str(offset),
                "include": "journals,attachments,custom_fields",
                "updated_on": f">={since_str}",
            }
            data = await self._get_json("/issues.json", params=params)
            issues = data.get("issues") or []
            if not issues:
                break
            for raw in issues:
                issue = _parse_issue(raw)
                # Server-side until filter: drop issues updated after until.
                if issue.updated_on > until:
                    continue
                # Keyset dedup: skip if same timestamp and lower/equal id
                # than last seen (handles page-boundary duplicates).
                if (
                    last_updated_on is not None
                    and issue.updated_on == last_updated_on
                    and issue.id <= last_id
                ):
                    continue
                last_updated_on = issue.updated_on
                last_id = issue.id
                yield issue
            total = data.get("total_count", 0)
            offset += limit
            if offset >= total:
                break

    async def iter_wiki_pages(
        self,
        project_id: int | str,
        since: datetime,
        until: datetime,
    ) -> AsyncIterator[RedmineWikiPage]:
        """Yield wiki pages updated within ``[since, until]``, latest-only.

        Per spec open question #1 resolution: we fetch the current version only.
        """
        index_data = await self._get_json(
            f"/projects/{project_id}/wiki/index.json"
        )
        pages = index_data.get("wiki_pages") or []
        for page_stub in pages:
            title = page_stub.get("title", "")
            updated_on_raw = page_stub.get("updated_on")
            updated_on = _parse_dt(updated_on_raw)
            if updated_on is None:
                continue
            if updated_on < since or updated_on > until:
                continue
            # Fetch full page content.
            try:
                page_data = await self._get_json(
                    f"/projects/{project_id}/wiki/{title}.json"
                )
            except (PermissionError, RuntimeError):
                logger.warning(
                    "RedmineClient: could not fetch wiki page %r for project %s",
                    title, project_id,
                )
                continue
            wp = page_data.get("wiki_page") or {}
            created_on = _parse_dt(wp.get("created_on"))
            author_raw = wp.get("author")
            author = _parse_user_ref(author_raw) if author_raw else None
            yield RedmineWikiPage(
                title=title,
                project_id=int(project_id),
                updated_on=updated_on,
                created_on=created_on,
                text=wp.get("text") or "",
                version=wp.get("version", 1),
                author=author,
            )

    async def fetch_attachment(self, content_url: str) -> bytes:
        """Fetch attachment bytes from ``content_url`` using API auth headers.

        Returns raw bytes on success. Raises ``RuntimeError`` on non-2xx.
        The adapter catches the error and logs a skip per spec open-q #2.
        """
        headers = self._build_auth_header()
        if not self.verify_ssl:
            self._emit_ssl_audit()
        async with self._make_session() as session:
            async with session.get(
                content_url,
                headers=headers,
                ssl=False if not self.verify_ssl else None,
            ) as resp:
                if not (200 <= resp.status < 300):
                    raise RuntimeError(
                        f"Attachment fetch failed: HTTP {resp.status} for {content_url}"
                    )
                return await resp.read()

    def is_issue_closed(
        self, issue: RedmineIssue, closed_status_ids: frozenset[int] | None = None
    ) -> bool | None:
        """Determine whether an issue is closed.

        Uses ``issue.status.is_closed`` when present; falls back to
        ``issue.status.id in closed_status_ids`` for pre-4.x instances.
        Returns ``None`` (unknown) when both sources are unavailable.
        """
        if issue.status.is_closed is not None:
            return issue.status.is_closed
        effective_ids = closed_status_ids if closed_status_ids is not None \
            else self.closed_status_ids
        if not effective_ids:
            # Neither is_closed nor fallback ids: genuinely unknown.
            return None
        if not self._warned_is_closed_fallback:
            self._warned_is_closed_fallback = True
            logger.warning(
                "RedmineClient: status.is_closed absent on this instance; "
                "falling back to closed_status_ids=%s. "
                "Upgrade Redmine to 4.x+ to eliminate this warning.",
                sorted(effective_ids),
            )
        return issue.status.id in effective_ids

    @staticmethod
    def attachment_eligible(attachment: RedmineAttachment) -> bool:
        """Return True if the attachment should be ingested (Phase-1 policy).

        MIME must be text/* or JSON/XML/YAML, and filesize ≤ 1 MiB.
        """
        mime = attachment.content_type.lower().split(";")[0].strip()
        mime_ok = mime.startswith(_ATTACHMENT_MIME_PREFIXES) or \
            mime in _ATTACHMENT_MIME_EXACT
        size_ok = attachment.filesize <= _ATTACHMENT_MAX_BYTES
        return mime_ok and size_ok


class _NullContextSession:
    """Wraps an injected session so it can be used as an async context manager."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_):
        pass
