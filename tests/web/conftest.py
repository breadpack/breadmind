"""Web test shared fixtures.

Re-exports KB fixtures so tests under ``tests/web/`` can use the same
Postgres container, seeded project, and fake Slack client as the KB tests.

pytest 8 discourages ``pytest_plugins`` in non-root conftest files, so we
import the fixture functions explicitly — each imported name becomes a
fixture scoped to this package.

Also defines lightweight fixtures (``web_app_client``, ``seeded_jobs``)
used by tests that exercise the full FastAPI stack via ``TestClient``
against ``breadmind.web.app.WebApp`` but do not need Postgres.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.kb.conftest import (  # noqa: F401
    db,
    fake_slack_client,
    pg_container,
    seeded_project,
)


@pytest.fixture
def web_app_client() -> TestClient:
    """Build a ``WebApp`` with auth enabled and a fresh ``JobTracker``.

    The ``AuthManager`` constructor derives ``enabled`` from
    ``bool(password_hash)`` so we only need to pass the hash. The
    module-level ``JobTracker._instance`` singleton is reset before and
    after each test so seeded rows from neighbouring tests don't leak.
    """
    from breadmind.coding.job_tracker import JobTracker
    from breadmind.web.app import WebApp
    from breadmind.web.auth import AuthManager

    # Reset the singleton so tests don't share state.
    JobTracker._instance = None

    auth = AuthManager(password_hash=AuthManager.hash_password("p"))
    app_wrapper = WebApp(
        message_handler=AsyncMock(return_value={"response": "ok", "agent": "test"}),
        auth=auth,
    )
    client = TestClient(app_wrapper.app)
    try:
        yield client
    finally:
        JobTracker._instance = None


@pytest.fixture
def seeded_jobs(web_app_client):
    """Seed two coding jobs owned by different users on the singleton tracker."""
    from breadmind.coding.job_tracker import JobTracker

    tracker = JobTracker.get_instance()
    tracker.create_job("alice-job-1", "p", "c", "x", user="alice", channel="")
    tracker.create_job("bob-job-1", "p", "c", "x", user="bob", channel="")
    return tracker
