"""Web test shared fixtures.

Re-exports KB fixtures so tests under ``tests/web/`` can use the same
Postgres container, seeded project, and fake Slack client as the KB tests.

pytest 8 discourages ``pytest_plugins`` in non-root conftest files, so we
import the fixture functions explicitly — each imported name becomes a
fixture scoped to this package.
"""
from __future__ import annotations

from tests.kb.conftest import (  # noqa: F401
    db,
    fake_slack_client,
    pg_container,
    seeded_project,
)
