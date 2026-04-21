"""Shared fixtures for KB connector tests (fake extractor/review, in-memory DB, VCR)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import vcr

CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture
def vcr_config() -> vcr.VCR:
    """Return a VCR instance configured for connector tests."""
    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode="none",
        match_on=["method", "scheme", "host", "port", "path", "query"],
        filter_headers=["authorization"],
    )


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
