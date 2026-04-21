"""Confluence REST ingestion connector.

Incrementally polls Atlassian Confluence Cloud/Server for pages updated
since the stored cursor, converts storage-format HTML to Markdown, and
feeds each page through the KnowledgeExtractor + ReviewQueue pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

import aiohttp
from markdownify import markdownify as md

from breadmind.kb import metrics as kb_metrics
from breadmind.kb.connectors.base import BaseConnector, SyncResult
from breadmind.kb.connectors.rate_limit import (
    BudgetExceeded,
    HourlyPageBudget,
)

try:
    from breadmind.kb.types import SourceMeta  # provided by P3
except ImportError:  # pragma: no cover — defensive during parallel dev
    @dataclass(frozen=True)
    class SourceMeta:  # type: ignore[no-redef]
        source_type: str
        source_uri: str
        source_ref: str | None
        original_user: str | None
        extracted_from: str
        project_id: uuid.UUID

logger = logging.getLogger(__name__)


def html_to_markdown(html: str) -> str:
    """Convert Confluence storage-format HTML to Markdown.

    Uses markdownify with ATX headings and fenced code blocks. Keeps
    tables in GitHub-style pipe syntax for downstream LLM readability.
    """
    return md(
        html or "",
        heading_style="ATX",
        code_language_callback=lambda el: (
            el.get("class", [""])[0].removeprefix("language-")
            if el.get("class") else ""
        ),
        bullets="-",
    ).strip()


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space_key: str
    web_url: str
    storage_html: str
    version_when: str  # ISO timestamp


class ConfluenceConnector(BaseConnector):
    """Ingest Confluence pages for one space into the KB review queue."""

    connector_name: ClassVar[str] = "confluence"

    _BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800)  # 1m, 5m, 30m
    _PAGE_LIMIT: int = 50

    def __init__(
        self,
        *,
        db: Any,
        base_url: str,
        credentials_ref: str,
        extractor: Any,
        review_queue: Any,
        vault: Any,
        budget: HourlyPageBudget | None = None,
        session: aiohttp.ClientSession | None = None,
        audit_log: Any | None = None,
    ) -> None:
        super().__init__(db)
        if not base_url.lower().startswith("https://"):
            raise ValueError("base_url must use https://")
        self._base_url = base_url.rstrip("/")
        self._credentials_ref = credentials_ref
        self._extractor = extractor
        self._review_queue = review_queue
        self._vault = vault
        self._budget = budget or HourlyPageBudget()
        self._session_override = session
        self._audit_log = audit_log

    # ── Credential handling ───────────────────────────────────────────

    async def _build_auth_header(self) -> str:
        raw = await self._vault.retrieve(self._credentials_ref)
        if not raw:
            raise RuntimeError(
                f"Confluence credential not in vault: {self._credentials_ref}"
            )
        # Stored format: "email:api_token"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    # ── HTTP / pagination ─────────────────────────────────────────────

    def _acquire_session(self) -> aiohttp.ClientSession:
        if self._session_override is not None:
            return self._session_override
        return aiohttp.ClientSession()

    async def _release_session(self, session: aiohttp.ClientSession) -> None:
        # Only close sessions we created ourselves.
        if self._session_override is None:
            await session.close()

    async def _get_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict | None,
        auth: str,
    ):
        """GET with Retry-After + exponential backoff on 429/5xx."""
        backoffs = list(self._BACKOFF_SECONDS)
        while True:
            async with session.get(
                url, params=params, headers={"Authorization": auth}
            ) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "0"))
                    wait = retry_after if retry_after > 0 else (
                        backoffs.pop(0) if backoffs else self._BACKOFF_SECONDS[-1]
                    )
                    logger.warning(
                        "Confluence 429; sleeping %ds (Retry-After=%s)",
                        wait, resp.headers.get("Retry-After"),
                    )
                    await asyncio.sleep(wait)
                    continue
                if 500 <= resp.status < 600 and backoffs:
                    wait = backoffs.pop(0)
                    logger.warning("Confluence %d; sleeping %ds", resp.status, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return await resp.json()

    async def _fetch_pages(
        self,
        space_key: str,
        cursor: str | None,
    ):
        """Async generator yielding ``ConfluencePage`` objects."""
        auth = await self._build_auth_header()
        session = self._acquire_session()
        try:
            params: dict[str, Any] = {
                "spaceKey": space_key,
                "expand": "body.storage,version",
                "limit": self._PAGE_LIMIT,
            }
            if cursor:
                params["updated-since"] = cursor
            url = f"{self._base_url}/rest/api/content"

            while True:
                payload = await self._get_with_retry(session, url, params, auth)
                for raw in payload.get("results", []):
                    yield self._to_page(raw)
                next_path = (payload.get("_links") or {}).get("next")
                if not next_path:
                    return
                # Atlassian returns relative path; drop query from base
                url = f"{self._base_url}{next_path}"
                params = None  # Next URL already includes the query string.
        finally:
            await self._release_session(session)

    @staticmethod
    def _to_page(raw: dict) -> ConfluencePage:
        webui = ((raw.get("_links") or {}).get("webui")) or ""
        return ConfluencePage(
            id=str(raw["id"]),
            title=raw.get("title", ""),
            space_key=(raw.get("space") or {}).get("key", ""),
            web_url=webui,
            storage_html=((raw.get("body") or {}).get("storage") or {}).get("value", ""),
            version_when=(raw.get("version") or {}).get("when", ""),
        )

    # ── Chunking / source meta ────────────────────────────────────────

    _CHUNK_CHAR_BUDGET: ClassVar[int] = 4000  # ~1k tokens @ 4 chars/token

    @staticmethod
    def _chunk_markdown(text: str, budget: int) -> list[str]:
        """Split markdown by paragraph boundaries, respecting ``budget``."""
        if not text:
            return []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for p in paragraphs:
            if size + len(p) > budget and buf:
                chunks.append("\n\n".join(buf))
                buf, size = [], 0
            buf.append(p)
            size += len(p) + 2
        if buf:
            chunks.append("\n\n".join(buf))
        return chunks

    def _build_source_meta(
        self, page: ConfluencePage, project_id: uuid.UUID
    ) -> SourceMeta:
        return SourceMeta(
            source_type="confluence",
            source_uri=f"{self._base_url}{page.web_url}"
            if page.web_url.startswith("/") else page.web_url,
            source_ref=page.id,
            original_user=None,
            extracted_from="confluence_sync",
            project_id=project_id,
        )

    # ── Sync ──────────────────────────────────────────────────────────

    async def _do_sync(
        self,
        project_id: uuid.UUID,
        scope_key: str,
        cursor: str | None,
    ) -> SyncResult:
        logger.info(
            "confluence.sync.start",
            extra={"project_id": str(project_id), "scope_key": scope_key,
                   "cursor": cursor},
        )
        processed = 0
        errors = 0
        max_when = cursor or ""

        async for page in self._fetch_pages(scope_key, cursor):
            try:
                await self._budget.consume(project_id, count=1)
            except BudgetExceeded as exc:
                logger.warning("Page budget hit: %s", exc)
                await self._audit("connector_error", project_id, {
                    "connector": self.connector_name,
                    "scope_key": scope_key,
                    "reason": "budget_exceeded",
                    "detail": str(exc),
                })
                break

            try:
                markdown = html_to_markdown(page.storage_html)
                meta = self._build_source_meta(page, project_id)
                for chunk in self._chunk_markdown(markdown, self._CHUNK_CHAR_BUDGET):
                    candidates = await self._extractor.extract(chunk, meta)
                    for cand in candidates or []:
                        await self._review_queue.enqueue(cand)
                processed += 1
            except Exception as exc:  # noqa: BLE001 — per-page isolation
                errors += 1
                logger.exception("Confluence page %s failed", page.id)
                await self._audit("connector_error", project_id, {
                    "connector": self.connector_name,
                    "scope_key": scope_key,
                    "page_id": page.id,
                    "detail": str(exc),
                })

            if page.version_when and page.version_when > max_when:
                max_when = page.version_when

        # After the main page-iteration finishes, scan for retirements:
        # any Confluence-backed kb_sources row that now 404s on the server
        # is flagged stale and a retirement candidate is enqueued for review.
        await self._scan_retirements(project_id, scope_key)

        # Publish breadmind_kb_size_bytes so ops dashboards see the post-sync
        # KB volume without waiting for a separate scheduled refresh.
        try:
            await self.refresh_size_metric()
        except Exception:  # pragma: no cover — metrics must never break prod
            logger.exception("refresh_size_metric failed")

        logger.info(
            "confluence.sync.done",
            extra={"project_id": str(project_id), "scope_key": scope_key,
                   "processed": processed, "errors": errors,
                   "new_cursor": max_when or (cursor or "")},
        )
        return SyncResult(
            new_cursor=max_when or (cursor or ""),
            processed=processed,
            errors=errors,
        )

    # ── Retirement scan ───────────────────────────────────────────────

    async def _known_source_refs(
        self, project_id: uuid.UUID
    ) -> list[tuple[int, int, str]]:
        """Return ``(source_id, knowledge_id, source_ref)`` for live confluence
        sources under ``project_id`` (excluding superseded knowledge rows)."""
        rows = await self._db.fetch(
            """
            SELECT s.id, s.knowledge_id, s.source_ref
              FROM kb_sources s
              JOIN org_knowledge k ON k.id = s.knowledge_id
             WHERE s.source_type = 'confluence'
               AND k.project_id = $1
               AND k.superseded_by IS NULL
            """,
            project_id,
        )
        return [
            (row["id"], row["knowledge_id"], row["source_ref"])
            for row in rows
        ]

    async def _page_exists(
        self,
        session: aiohttp.ClientSession,
        auth: str,
        page_id: str,
    ) -> bool:
        """Probe ``GET /rest/api/content/{page_id}``.

        404 → False; any other non-2xx raises; 2xx → True. Intentionally
        does not use :meth:`_get_with_retry` — a gone page must not trigger
        the standard 429/5xx backoff loop for each missing reference.
        """
        url = f"{self._base_url}/rest/api/content/{page_id}"
        async with session.get(url, headers={"Authorization": auth}) as resp:
            if resp.status == 404:
                return False
            resp.raise_for_status()
            return True

    async def _scan_retirements(
        self,
        project_id: uuid.UUID,
        scope_key: str,
    ) -> None:
        """Flag kb_sources whose Confluence page is gone as stale and enqueue
        a retirement review candidate for each."""
        refs = await self._known_source_refs(project_id)
        if not refs:
            return
        auth = await self._build_auth_header()
        session = self._acquire_session()
        try:
            for source_id, knowledge_id, source_ref in refs:
                if await self._page_exists(session, auth, source_ref):
                    continue
                # Mark the source row stale (captured_at = now()).
                await self._db.execute(
                    "UPDATE kb_sources SET captured_at = now() WHERE id = $1",
                    source_id,
                )
                await self._review_queue.enqueue({
                    "project_id": project_id,
                    "proposed_title": (
                        f"Retire knowledge for gone page {source_ref}"
                    ),
                    "proposed_body": (
                        "Confluence page no longer exists. "
                        "Review and retire via superseded_by."
                    ),
                    "proposed_category": "retirement",
                    "status": "needs_edit",
                    "confidence": 0.5,
                    "sources_json": [{
                        "source_type": "confluence",
                        "source_uri": f"{self._base_url}/pages/{source_ref}",
                        "source_ref": source_ref,
                    }],
                    "extracted_from": "confluence_retirement",
                    "original_user": None,
                    "knowledge_id": knowledge_id,
                })
        finally:
            await self._release_session(session)

    async def _audit(
        self,
        action: str,
        project_id: uuid.UUID,
        metadata: dict,
    ) -> None:
        if self._audit_log is None:
            return
        try:
            await self._audit_log.record(
                actor=f"connector:{self.connector_name}",
                action=action,
                project_id=project_id,
                metadata=metadata,
            )
        except Exception:
            logger.exception("kb_audit_log write failed")

    # ── Metrics ───────────────────────────────────────────────────────

    async def refresh_size_metric(self) -> None:
        """Aggregate ``org_knowledge`` body bytes per project and publish
        to the ``breadmind_kb_size_bytes{project=...}`` Prometheus gauge.

        Runs at the tail of every :meth:`_do_sync` pass so the gauge
        stays fresh across connector iterations, and can also be called
        standalone from the P5 build-for-tests harness.
        """
        rows = await self._db.fetch(
            "SELECT project_id, COALESCE(SUM(OCTET_LENGTH(body)),0) AS b "
            "FROM org_knowledge WHERE superseded_by IS NULL "
            "GROUP BY project_id"
        )
        for r in rows:
            try:
                kb_metrics.set_kb_size_bytes(
                    project=str(r["project_id"]),
                    bytes_=int(r["b"]),
                )
            except Exception:  # pragma: no cover — metrics must never break prod
                logger.exception("set_kb_size_bytes failed for %s", r)

    @classmethod
    def build_for_e2e(
        cls,
        *,
        db,
        fixtures_path: str,
        project_name: str = "pilot-alpha",
    ) -> "_E2EConfluenceFacade":
        """Factory for the Task 21 E2E test — skips HTTP entirely.

        Reads Confluence page fixtures from ``fixtures_path`` (the file
        :mod:`scripts.seed_pilot_data` writes at sync time), converts each
        page to an :class:`ExtractedCandidate`, and enqueues them through
        a real :class:`ReviewQueue` against the testcontainers Postgres.

        The returned facade exposes:

        * ``sync_once()`` — processes the fixture and returns the
          number of candidates enqueued.
        * ``auto_approve_seed_candidates(reviewer)`` — approves every
          pending candidate for the project via the real approve()
          path (with a monkey-patched embedder).
        """
        return _E2EConfluenceFacade(
            db=db, fixtures_path=fixtures_path, project_name=project_name,
        )

    @classmethod
    async def build_for_tests(
        cls,
        *,
        project_id: str = "proj-a",
        body_bytes: int = 0,
    ) -> "ConfluenceConnector":
        """Factory for metric-path tests.

        Returns a ConfluenceConnector whose DB stub emits a single
        ``SELECT project_id, SUM(OCTET_LENGTH(body))`` row so a bare
        :meth:`refresh_size_metric` call can drive the gauge without a
        live postgres fixture or aiohttp session.
        """
        class _SizeDB:
            async def fetch(self, sql: str, *_args: Any):
                if "org_knowledge" in sql and "OCTET_LENGTH(body)" in sql:
                    return [{"project_id": project_id, "b": body_bytes}]
                return []

            async def fetchrow(self, *_a: Any, **_kw: Any):
                return None

            async def execute(self, *_a: Any, **_kw: Any):
                return None

        class _NullVault:
            async def retrieve(self, *_a, **_kw):
                return None

        class _NullExtractor:
            async def extract(self, *_a, **_kw):
                return []

        class _NullReviewQueue:
            async def enqueue(self, *_a, **_kw):
                return 0

        return cls(
            db=_SizeDB(),
            base_url="https://test.local",
            credentials_ref="test:none",
            extractor=_NullExtractor(),
            review_queue=_NullReviewQueue(),
            vault=_NullVault(),
        )


class _E2EConfluenceFacade:
    """Fixture-driven Confluence connector facade for the E2E test.

    Reads the JSON written by :mod:`scripts.seed_pilot_data` (which
    contains ``{id, title, space, body}`` entries), synthesises an
    :class:`ExtractedCandidate` per page, and enqueues each via a real
    :class:`ReviewQueue`. Skips HTTP / auth / retry logic entirely —
    those paths are covered by :mod:`tests/kb/connectors/` unit tests.
    """

    def __init__(
        self, *, db, fixtures_path: str, project_name: str,
    ) -> None:
        self._db = db
        self._fixtures_path = fixtures_path
        self._project_name = project_name
        self._queue = None
        self._project_id = None

    async def _ensure(self) -> None:
        if self._queue is not None:
            return
        from breadmind.kb import e2e_factories as ef
        from breadmind.kb import review_queue as rq_mod
        from breadmind.kb.review_queue import ReviewQueue

        await ef.ensure_e2e_schema(self._db)
        pool = ef.AsyncpgConnectionPool(self._db)
        self._project_id = await ef.resolve_project_id(
            self._db, self._project_name,
        )
        # Monkey-patch the embedder shim (same pattern as
        # ReviewQueue.build_for_e2e) so approve() can produce a pgvector.
        embedder = ef.StableEmbedder()

        async def _embed(text: str):
            return await embedder.encode(text)

        rq_mod._embed_text = _embed  # type: ignore[assignment]
        self._queue = ReviewQueue(pool, slack_client=None)

    async def sync_once(self) -> int:
        """Read fixture pages and enqueue one candidate per page.

        Returns the number of enqueued candidates.
        """
        from breadmind.kb import e2e_factories as ef
        from breadmind.kb.types import ExtractedCandidate, Source

        await self._ensure()
        pages = ef.load_confluence_fixtures(self._fixtures_path)
        enqueued = 0
        for p in pages:
            cand = ExtractedCandidate(
                proposed_title=p.get("title", ""),
                proposed_body=p.get("body", ""),
                proposed_category="bug_fix"
                if "leak" in (p.get("title", "") + p.get("body", "")).lower()
                else "onboarding",
                confidence=0.9,
                sources=[Source(
                    type="confluence",
                    uri=f"https://wiki/{p.get('space', 'X')}/{p.get('id', '?')}",
                    ref=p.get("id"),
                )],
                original_user=None,
                project_id=self._project_id,
                sensitive_flag=False,
            )
            await self._queue.enqueue(cand)
            enqueued += 1
        return enqueued

    async def auto_approve_seed_candidates(self, *, reviewer: str) -> list[int]:
        """Approve every pending candidate for the project.

        Returns the list of new ``org_knowledge.id`` values so tests can
        assert on specific rows if needed.
        """
        await self._ensure()
        pending_ids = [
            r["id"] for r in await self._db.fetch(
                "SELECT id FROM promotion_candidates "
                "WHERE project_id=$1 AND status='pending'",
                self._project_id,
            )
        ]
        kids: list[int] = []
        for cid in pending_ids:
            kid = await self._queue.approve(
                candidate_id=int(cid), reviewer=reviewer,
            )
            kids.append(int(kid))
        return kids
