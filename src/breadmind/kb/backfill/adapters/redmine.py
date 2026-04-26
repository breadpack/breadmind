"""RedmineBackfillAdapter — BackfillJob implementation for on-prem Redmine.

Emits three row shapes per Redmine project:
  - Issue anchor rows   (source_kind="redmine_issue",   parent_ref=None)
  - Journal child rows  (source_kind="redmine_journal", parent_ref="redmine_issue:<id>")
  - Wiki page rows      (source_kind="redmine_wiki",    parent_ref=None)
  - Attachment rows     (source_kind="redmine_attachment", parent_ref=... — Phase-1)

All HTTP and on-prem variability lives in RedmineClient; this module is pure
orchestration and filtering logic.
"""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, ClassVar

from breadmind.kb.backfill.adapters.redmine_client import RedmineClient
from breadmind.kb.backfill.adapters.redmine_types import (
    RedmineIssue,
    RedmineJournal,
    RedmineWikiPage,
)
from breadmind.kb.backfill.base import BackfillItem, BackfillJob

logger = logging.getLogger(__name__)

# Canonical skip-reason keys (D1).
_SR_PRIVATE_NOTES = "private_notes"
_SR_METADATA_ONLY = "metadata_only_journal"
_SR_EMPTY_DESC = "empty_description"
_SR_CLOSED_OLD = "closed_old"
_SR_ACL_LOCK = "acl_lock"
_SR_AUTO_GENERATED = "auto_generated"


class RedmineBackfillAdapter(BackfillJob):
    """Backfill adapter for on-prem Redmine (issues + journals + wiki).

    Spec: docs/superpowers/specs/2026-04-26-backfill-redmine-design.md

    Args (beyond BackfillJob base):
        client: Injected ``RedmineClient`` instance.
        vault: Credential vault dict (passed to client.from_vault if client is None).
        audit_log: Callable for security-relevant audit events.
    """

    source_kind: ClassVar[str] = "redmine_issue"

    # Default filter thresholds — overridable via ``config`` dict.
    _DEFAULT_MIN_DESCRIPTION_CHARS: ClassVar[int] = 40
    _DEFAULT_MIN_JOURNAL_CHARS: ClassVar[int] = 30
    _DEFAULT_CLOSED_ONLY: ClassVar[bool] = True

    def __init__(
        self,
        *,
        client: RedmineClient,
        vault=None,
        audit_log=None,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._client = client
        self._vault = vault
        self._audit_log = audit_log
        # Populated by prepare().
        self._membership_snapshot: frozenset[tuple[int, int, str]] = frozenset()
        self._bot_authors_re: re.Pattern | None = None
        # Per-job attachment-skip counter (spec open-q #2).
        self._attachment_skipped: int = 0
        # Resume cursor support.
        self._resume_cursor: str | None = None

    # ------------------------------------------------------------------
    # BackfillJob contract
    # ------------------------------------------------------------------

    def instance_id_of(self, source_filter: dict[str, Any]) -> str:
        """Return ``sha256(base_url)[:16]`` — stable, no timestamp salt (D5)."""
        return hashlib.sha256(
            self._client.base_url.encode()
        ).hexdigest()[:16]

    def cursor_of(self, item: BackfillItem) -> str:
        """Encode cursor as ``<iso_updated_at>:<issue_id>`` (D2).

        Both anchor and journal rows encode to the *parent issue id* so a
        resume can forward ``since`` to the correct position.
        """
        # source_native_id for journal is "<issue_id>#note-<journal_id>"; split on '#'.
        issue_id = item.source_native_id.split("#")[0]
        return f"{item.source_updated_at.isoformat()}:{issue_id}"

    async def prepare(self) -> None:
        """Snapshot project memberships before discover begins (C1).

        Raises ``PermissionError`` if any project is inaccessible (adapts
        spec step 2 fallback behaviour).
        """
        project_ids = self._project_ids_from_filter()
        try:
            await self._client.verify_identity()
        except Exception as exc:
            raise PermissionError(
                f"Redmine identity verification failed: {exc}"
            ) from exc

        snapshot: set[tuple[int, int, str]] = set()
        for pid in project_ids:
            try:
                members = await self._client.fetch_memberships(pid)
            except PermissionError as exc:
                raise PermissionError(
                    f"Redmine project {pid} membership fetch forbidden: {exc}"
                ) from exc
            for m in members:
                for role in (m.role_names or [""]):
                    snapshot.add((m.project_id, m.user_id, role))
        self._membership_snapshot = frozenset(snapshot)

        # Compile bot-authors regex if configured.
        bot_pattern = (self.config or {}).get("bot_authors_re")
        if bot_pattern:
            self._bot_authors_re = re.compile(bot_pattern)

    async def discover(self) -> AsyncIterator[BackfillItem]:  # type: ignore[override]
        """Yield BackfillItems: issue anchors, journal children, wiki, attachments."""
        project_ids = self._project_ids_from_filter()
        include = set(self.source_filter.get("include") or ["issues", "wiki"])

        # Resume: parse cursor to adjust since window.
        since = self.since
        resume_cursor = self._resume_cursor
        if resume_cursor:
            since = self._parse_resume_cursor(resume_cursor, since)

        if "issues" in include:
            for pid in project_ids:
                async for issue in self._client.iter_issues(pid, since, self.until):
                    # Resume: skip anchor rows that are at/before the cursor.
                    if resume_cursor and self._issue_at_or_before_cursor(
                        issue, resume_cursor
                    ):
                        continue
                    # Yield anchor row.
                    yield self._build_anchor(issue)
                    # Yield journal child rows.
                    for idx, journal in enumerate(issue.journals, start=1):
                        # In-memory time filter for journals (spec D4).
                        if journal.created_on < since or journal.created_on > self.until:
                            continue
                        if resume_cursor and self._journal_before_cursor(
                            issue, journal, resume_cursor
                        ):
                            continue
                        yield self._build_journal(issue, journal, idx)
                    # Yield attachment rows when include contains "attachments".
                    if "attachments" in include:
                        async for att_item in self._discover_attachments(issue):
                            yield att_item

        if "wiki" in include:
            for pid in project_ids:
                try:
                    async for wp in self._client.iter_wiki_pages(
                        pid, since, self.until
                    ):
                        yield self._build_wiki(wp)
                except (PermissionError, RuntimeError) as exc:
                    logger.warning(
                        "RedmineBackfillAdapter: wiki pages unavailable for "
                        "project %s: %s", pid, exc,
                    )

    def filter(self, item: BackfillItem) -> bool:
        """Apply Redmine-specific signal filters (spec §Signal Filters).

        Order per spec: private_notes → metadata_only_journal → closed_old
        → empty_description → auto_generated → tracker_allow → acl_lock.

        Returns True (keep) or False (drop). Sets ``extra["_skip_reason"]`` on drop.
        """
        cfg = self.config or {}
        kind = item.extra.get("_kind", "")

        # 1. private_notes — hard drop.
        if item.extra.get("private_notes"):
            item.extra["_skip_reason"] = _SR_PRIVATE_NOTES
            return False

        # 2. metadata_only_journal — no notes text.
        if kind == "journal" and item.extra.get("metadata_only"):
            item.extra["_skip_reason"] = _SR_METADATA_ONLY
            return False

        # 3. closed_old — skip open issues (closed_only default True).
        if kind == "anchor":
            closed_only = cfg.get("closed_only", self._DEFAULT_CLOSED_ONLY)
            if closed_only:
                is_closed = item.extra.get("is_closed_resolved")
                if is_closed is False:
                    # Definitely open.
                    item.extra["_skip_reason"] = _SR_CLOSED_OLD
                    return False
                # is_closed=None → unknown (pre-4.x, no closed_status_ids):
                # downgrade to no-op rather than crash.

        # 4. empty_description (min chars).
        if kind == "anchor":
            min_chars = int(cfg.get("min_description_chars",
                                    self._DEFAULT_MIN_DESCRIPTION_CHARS))
            if len((item.body or "").strip()) < min_chars:
                item.extra["_skip_reason"] = _SR_EMPTY_DESC
                return False
        elif kind == "journal":
            min_chars = int(cfg.get("min_journal_chars",
                                    self._DEFAULT_MIN_JOURNAL_CHARS))
            if len((item.body or "").strip()) < min_chars:
                item.extra["_skip_reason"] = _SR_EMPTY_DESC
                return False

        # 5. auto_generated — bot authors regex.
        if self._bot_authors_re and item.author:
            login = item.extra.get("author_login") or item.author
            if self._bot_authors_re.search(login):
                item.extra["_skip_reason"] = _SR_AUTO_GENERATED
                return False

        # 6. tracker_allow — optional allowlist.
        tracker_allow: list[str] | None = cfg.get("tracker_allow")
        if tracker_allow and kind == "anchor":
            tracker = item.extra.get("tracker", "")
            if tracker not in tracker_allow:
                item.extra["_skip_reason"] = _SR_AUTO_GENERATED
                return False

        # 7. acl_lock — membership snapshot lookup (no HTTP in filter).
        project_id = item.extra.get("project_id")
        if project_id is not None and item.author:
            try:
                author_id = int(item.author)
            except (ValueError, TypeError):
                author_id = -1
            if author_id >= 0:
                in_project = any(
                    m_pid == project_id and m_uid == author_id
                    for m_pid, m_uid, _ in self._membership_snapshot
                )
                if not in_project:
                    item.extra["_skip_reason"] = _SR_ACL_LOCK
                    return False

        return True

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_anchor(self, issue: RedmineIssue) -> BackfillItem:
        body = f"{issue.subject}\n\n{issue.description}"
        is_closed = self._client.is_issue_closed(issue)
        return BackfillItem(
            source_kind="redmine_issue",
            source_native_id=str(issue.id),
            source_uri=f"{self._client.base_url}/issues/{issue.id}",
            source_created_at=issue.created_on,
            source_updated_at=issue.updated_on,
            title=issue.subject,
            body=body,
            author=str(issue.author.id) if issue.author else None,
            parent_ref=None,
            extra={
                "_kind": "anchor",
                "tracker": issue.tracker_name,
                "status_id": issue.status.id,
                "is_closed_resolved": is_closed,
                "project_id": issue.project_id,
                "custom_fields": [
                    {"id": cf.id, "name": cf.name, "value": cf.value}
                    for cf in issue.custom_fields
                ],
                "author_login": issue.author.login if issue.author else None,
            },
        )

    def _build_journal(
        self,
        issue: RedmineIssue,
        journal: RedmineJournal,
        display_index: int,
    ) -> BackfillItem:
        return BackfillItem(
            source_kind="redmine_journal",
            source_native_id=f"{issue.id}#note-{journal.id}",
            source_uri=(
                f"{self._client.base_url}/issues/{issue.id}"
                f"#note-{display_index}"
            ),
            source_created_at=journal.created_on,
            source_updated_at=journal.created_on,
            title=f"[{issue.subject}] note #{display_index}",
            body=journal.notes,
            author=str(journal.user.id) if journal.user else None,
            parent_ref=f"redmine_issue:{issue.id}",
            extra={
                "_kind": "journal",
                "private_notes": journal.private_notes,
                "metadata_only": not journal.notes.strip(),
                "project_id": issue.project_id,
                "author_login": (
                    journal.user.login
                    if journal.user and journal.user.login
                    else None
                ),
            },
        )

    def _build_wiki(self, wp: RedmineWikiPage) -> BackfillItem:
        title_safe = urllib.parse.quote(wp.title, safe="")
        native_id = f"{wp.project_id}:{title_safe}"
        created = wp.created_on or wp.updated_on
        return BackfillItem(
            source_kind="redmine_wiki",
            source_native_id=native_id,
            source_uri=(
                f"{self._client.base_url}/projects/{wp.project_id}"
                f"/wiki/{title_safe}"
            ),
            source_created_at=created,
            source_updated_at=wp.updated_on,
            title=wp.title,
            body=wp.text,
            author=str(wp.author.id) if wp.author else None,
            parent_ref=None,
            extra={
                "_kind": "wiki",
                "project_id": wp.project_id,
                "version": wp.version,
            },
        )

    async def _discover_attachments(
        self, issue: RedmineIssue
    ) -> AsyncIterator[BackfillItem]:
        """Yield eligible text attachments for an issue (spec open-q #2)."""
        for att in issue.attachments:
            if not RedmineClient.attachment_eligible(att):
                continue
            try:
                raw = await self._client.fetch_attachment(att.content_url)
                body = raw.decode("utf-8", errors="replace")
            except Exception as exc:
                logger.warning(
                    "RedmineBackfillAdapter: attachment %s skipped (%s)",
                    att.id, exc,
                )
                self._attachment_skipped += 1
                continue
            yield BackfillItem(
                source_kind="redmine_attachment",
                source_native_id=f"att:{att.id}",
                source_uri=att.content_url,
                source_created_at=att.created_on,
                source_updated_at=att.created_on,
                title=att.filename,
                body=body,
                author=str(att.author.id) if att.author else None,
                parent_ref=f"redmine_issue:{issue.id}",
                extra={
                    "_kind": "attachment",
                    "content_type": att.content_type,
                    "filesize": att.filesize,
                    "project_id": issue.project_id,
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _project_ids_from_filter(self) -> list[int | str]:
        pid = self.source_filter.get("project_id")
        if pid is None:
            raise ValueError(
                "RedmineBackfillAdapter: source_filter.project_id required"
            )
        return [pid]

    def _parse_resume_cursor(
        self, cursor: str, fallback: datetime
    ) -> datetime:
        """Parse ``<iso>:<issue_id>`` cursor, return since adjusted forward.

        Uses ``rsplit(":", 1)`` because the ISO timestamp itself contains
        colons (e.g. ``2025-09-10T00:00:00+00:00:42000``).
        """
        try:
            iso_part, _ = cursor.rsplit(":", 1)
            parsed = datetime.fromisoformat(
                iso_part.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            return max(fallback, parsed)
        except Exception:
            logger.warning(
                "RedmineBackfillAdapter: unparseable resume cursor %r; "
                "using original since=%s", cursor, fallback
            )
            return fallback

    def _issue_at_or_before_cursor(
        self, issue: RedmineIssue, cursor: str
    ) -> bool:
        """Return True if this issue (anchor) is at or before the resume cursor.

        Skips issues whose ``(updated_on, id)`` ≤ cursor keyset position,
        handling same-timestamp page-boundary collisions.
        """
        try:
            iso_part, cursor_issue_id = cursor.rsplit(":", 1)
            cursor_dt = datetime.fromisoformat(
                iso_part.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            c_id = int(cursor_issue_id)
        except Exception:
            return False
        if issue.updated_on < cursor_dt:
            return True
        if issue.updated_on == cursor_dt and issue.id <= c_id:
            return True
        return False

    def _journal_before_cursor(
        self,
        issue: RedmineIssue,
        journal: RedmineJournal,
        cursor: str,
    ) -> bool:
        """Return True if this journal is already covered by the resume cursor."""
        try:
            iso_part, cursor_issue_id = cursor.rsplit(":", 1)
            cursor_dt = datetime.fromisoformat(
                iso_part.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            c_id = int(cursor_issue_id)
        except Exception:
            return False
        # Skip journals belonging to issues that are strictly before the cursor.
        if issue.updated_on < cursor_dt:
            return True
        if issue.updated_on == cursor_dt and issue.id <= c_id:
            return True
        return False
