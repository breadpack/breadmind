"""Shared fixtures for KB connector tests (fake extractor/review, in-memory DB, VCR)."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import vcr

CASSETTE_DIR = Path(__file__).parent / "cassettes"

# Defense-in-depth secret scrubbers applied to cassette response bodies
# when operators record new cassettes (``record_mode="new_episodes"`` /
# ``"once"`` / ``"all"``). ``record_mode="none"`` never writes, so these
# are effectively no-ops for replay-only runs, but they belong in the
# shared config so a future re-record cannot accidentally commit secrets.
_SECRET_BODY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Email addresses (RFC 5322-ish; good enough for cassette scrubbing).
    (re.compile(rb"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
     b"scrubbed@example.com"),
    # Atlassian API tokens (ATATT prefix).
    (re.compile(rb"ATATT[A-Za-z0-9+/=_-]{20,}"), b"ATATT_REDACTED"),
    # Bearer tokens in JSON bodies.
    (re.compile(rb'"(access_token|refresh_token|api_token|apikey|api_key|secret)"\s*:\s*"[^"]+"'),
     b'"\\1": "REDACTED"'),
    # AWS-style keys (20-char uppercase) and long hex secrets.
    (re.compile(rb"AKIA[0-9A-Z]{16}"), b"AKIA_REDACTED"),
    # Slack tokens (xoxb-/xoxp-/xapp-/xoxa-).
    (re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"), b"xoxb-REDACTED"),
)


def _scrub_response_body(response: dict) -> dict:
    """VCR ``before_record_response`` hook: scrub secrets from response bodies.

    Runs ONLY when VCR is in a record mode; replay mode reads cassettes
    as-is and does not invoke this hook. Safe to call on any response
    shape — unknown body encodings pass through untouched.
    """
    try:
        body = response.get("body", {})
        raw = body.get("string")
        if not raw:
            return response
        as_bytes = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        scrubbed = as_bytes
        for pattern, repl in _SECRET_BODY_PATTERNS:
            scrubbed = pattern.sub(repl, scrubbed)
        if scrubbed != as_bytes:
            body["string"] = scrubbed if isinstance(raw, bytes) else scrubbed.decode(
                "utf-8", errors="replace",
            )
    except Exception:  # pragma: no cover — scrubber must never break recording
        pass
    return response


@pytest.fixture
def vcr_config() -> vcr.VCR:
    """Return a VCR instance configured for connector tests."""
    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode="none",
        match_on=["method", "scheme", "host", "port", "path", "query"],
        filter_headers=["authorization"],
        before_record_response=_scrub_response_body,
    )


@pytest.fixture
def scrub_response_body():
    """Expose the scrubber to tests for direct assertion."""
    return _scrub_response_body


@dataclass
class RecordedExtractCall:
    text: str
    source_meta: Any


@dataclass
class FakeExtractor:
    calls: list[RecordedExtractCall] = field(default_factory=list)

    async def extract(self, text: str, source_meta: Any) -> list[dict]:
        self.calls.append(RecordedExtractCall(text=text, source_meta=source_meta))
        return [
            {
                "title": "dummy",
                "content": text[:64],
                "source_type": source_meta.source_type,
                "source_uri": source_meta.source_uri,
                "source_ref": source_meta.source_ref,
                "extracted_from": source_meta.extracted_from,
                "original_user": source_meta.original_user,
                "project_id": source_meta.project_id,
            }
        ]


@dataclass
class FakeReviewQueue:
    enqueued: list[dict] = field(default_factory=list)

    async def enqueue(self, candidate: dict) -> int:
        self.enqueued.append(candidate)
        return len(self.enqueued)


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def fake_review_queue() -> FakeReviewQueue:
    return FakeReviewQueue()


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-8000-000000000001")


class InMemoryDB:
    """Minimal asyncpg-compatible stub for connector tests."""

    def __init__(self) -> None:
        self.sync_state: dict[tuple[str, str], dict] = {}
        self.kb_sources_stale: list[Any] = []

    async def fetchrow(self, sql: str, *args: Any):
        if "connector_sync_state" in sql and sql.lstrip().upper().startswith("SELECT"):
            return self.sync_state.get((args[0], args[1]))
        return None

    async def execute(self, sql: str, *args: Any):
        if "INSERT INTO connector_sync_state" in sql:
            connector, scope = args[0], args[1]
            row = {
                "connector": connector,
                "scope_key": scope,
                "project_id": args[2] if len(args) > 2 else None,
                "last_cursor": args[3] if len(args) > 3 else None,
                "last_run_at": args[4] if len(args) > 4 else None,
                "last_status": args[5] if len(args) > 5 else None,
                "last_error": args[6] if len(args) > 6 else None,
            }
            self.sync_state[(connector, scope)] = row
            return None
        if "UPDATE kb_sources" in sql:
            self.kb_sources_stale.append(args[0])
            return None
        return None

    async def fetch(self, sql: str, *args: Any):
        return []


@pytest.fixture
def mem_db() -> InMemoryDB:
    return InMemoryDB()
