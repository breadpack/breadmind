"""ConfluenceConnector tests (unit + vcr-backed integration)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientSession

from breadmind.kb.connectors.confluence import (
    ConfluenceConnector,
    ConfluencePage,
)
from breadmind.kb.connectors.rate_limit import HourlyPageBudget


class FakeVault:
    def __init__(self, mapping: dict[str, str]):
        self._m = mapping

    async def retrieve(self, cred_id: str) -> str | None:
        return self._m.get(cred_id)


async def test_connector_name_is_confluence():
    assert ConfluenceConnector.connector_name == "confluence"


async def test_basic_auth_header_uses_credential_vault(mem_db, fake_extractor,
                                                       fake_review_queue):
    vault = FakeVault({"confluence:pilot": "alice@example.com:TOKEN123"})
    conn = ConfluenceConnector(
        db=mem_db,
        base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:pilot",
        extractor=fake_extractor,
        review_queue=fake_review_queue,
        vault=vault,
    )
    header = await conn._build_auth_header()
    # "alice@example.com:TOKEN123" -> base64
    assert header.startswith("Basic ")
    import base64
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    assert decoded == "alice@example.com:TOKEN123"


async def test_connector_raises_if_credential_missing(mem_db, fake_extractor,
                                                      fake_review_queue):
    vault = FakeVault({})
    conn = ConfluenceConnector(
        db=mem_db,
        base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:missing",
        extractor=fake_extractor,
        review_queue=fake_review_queue,
        vault=vault,
    )
    with pytest.raises(RuntimeError, match="credential"):
        await conn._build_auth_header()
