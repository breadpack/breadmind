"""Tests for the slack-session resolution helper used by ``_run_slack`` and
``_run_resume`` in :mod:`breadmind.kb.backfill.cli`.

The helper bridges main.py's "I don't yet know which org_id needs a token"
constraint with the adapter's "I need a session NOW" expectation: the
sub-command handlers call it once they have ``args.org`` (or the resumed
row's ``org_id``) in hand and it returns either the explicitly-provided
session (preserved for e2e tests / production callers that pre-build one)
or a vault-backed :class:`SlackWebSession`.
"""
from __future__ import annotations

import uuid

from breadmind.kb.backfill.cli import _resolve_slack_session
from breadmind.connectors.slack_web import SlackWebSession


class _FakeVault:
    async def retrieve(self, ref: str) -> str | None:
        return "xoxb-test"


class _FakeSession:
    pass


def test_returns_provided_session_when_supplied() -> None:
    explicit = _FakeSession()
    org_id = uuid.uuid4()
    out = _resolve_slack_session(explicit, vault=_FakeVault(), org_id=org_id)
    assert out is explicit


def test_builds_vault_backed_session_when_none() -> None:
    org_id = uuid.uuid4()
    out = _resolve_slack_session(None, vault=_FakeVault(), org_id=org_id)
    assert isinstance(out, SlackWebSession)
    assert out._credentials_ref == f"slack:org:{org_id}"
