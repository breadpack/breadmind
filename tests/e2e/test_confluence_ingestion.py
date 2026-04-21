"""Task 21: E2E Confluence ingestion — fixture sync -> auto-approve -> query.

Reads the static Confluence page fixtures written by
``scripts/seed_pilot_data.py`` (to ``tests/e2e/fixtures/data/confluence_pages.json``),
runs them through a facade that emulates :class:`ConfluenceConnector` over
the fixture JSON (no HTTP, no aiohttp), auto-approves the enqueued
candidates, then verifies the query path finds them.

Note: the plan snippet imports
``breadmind.kb.confluence_connector.ConfluenceConnector`` but the
production path is ``breadmind.kb.connectors.confluence``. Use the
actual path.
"""
from __future__ import annotations

import pytest

from breadmind.kb.connectors.confluence import ConfluenceConnector
from breadmind.kb.query_pipeline import QueryPipeline


@pytest.mark.asyncio
async def test_confluence_scheduled_sync_then_query(db, redis, slack, llm):
    conn = ConfluenceConnector.build_for_e2e(
        db=db,
        fixtures_path="tests/e2e/fixtures/data/confluence_pages.json",
        project_name="pilot-alpha",
    )
    synced = await conn.sync_once()
    assert synced >= 1

    await conn.auto_approve_seed_candidates(reviewer="U-PILOT-00")

    llm.script = {"메모리 누수": "CL 12345에서 패치."}
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=llm)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-00", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 결제 모듈 메모리 누수 어떻게 고쳤지?",
    )
    assert "CL 12345" in slack.posted[-1]["text"]
