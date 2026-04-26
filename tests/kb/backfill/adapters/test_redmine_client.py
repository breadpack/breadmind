"""Unit tests for RedmineClient — Tasks 1–9.

All HTTP is mocked via a simple fake aiohttp session / response so no network
calls are made. Each test group maps to a plan task.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.adapters.redmine_client import (
    RedmineAuthError,
    RedmineClient,
    _BACKOFF_SECONDS,
)
from breadmind.kb.backfill.adapters.redmine_types import RedmineIssue, RedmineStatusRef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**kw) -> RedmineClient:
    defaults = dict(
        base_url="https://redmine.acme.internal",
        api_key="testkey123",
        auth_mode="api_key",
        verify_ssl=True,
        rate_limit_qps=100.0,  # high so pacing never blocks tests
    )
    defaults.update(kw)
    return RedmineClient(**defaults)


class _FakeResp:
    def __init__(self, status: int, body: dict, headers: dict | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def json(self, **kw):
        return self._body

    async def read(self):
        return json.dumps(self._body).encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _FakeSession:
    """Minimal aiohttp.ClientSession stub."""

    def __init__(self, responses: list[_FakeResp]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kw):
        self.calls.append((url, kw))
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


def _client_with_session(session, **kw) -> RedmineClient:
    return _make_client(_session=session, **kw)


# ---------------------------------------------------------------------------
# Task 1 — Client skeleton + credential load
# ---------------------------------------------------------------------------


class TestClientConstruction:
    def test_missing_base_url_raises(self):
        with pytest.raises(ValueError, match="base_url is required"):
            RedmineClient(base_url="", api_key="k", auth_mode="api_key")

    def test_base_url_must_start_with_https(self):
        with pytest.raises(ValueError, match="https://"):
            RedmineClient(
                base_url="http://redmine.acme.internal",
                api_key="k",
                auth_mode="api_key",
            )

    def test_api_key_required_for_api_key_mode(self):
        with pytest.raises(ValueError, match="api_key required"):
            RedmineClient(
                base_url="https://redmine.acme.internal",
                api_key=None,
                auth_mode="api_key",
            )

    def test_api_key_auth_header(self):
        client = _make_client(api_key="mykey")
        headers = client._build_auth_header()
        assert headers == {"X-Redmine-API-Key": "mykey"}

    def test_basic_auth_header(self):
        client = _make_client(
            api_key=None,
            auth_mode="basic",
            basic_user="alice",
            basic_password="secret",
        )
        headers = client._build_auth_header()
        expected = base64.b64encode(b"alice:secret").decode()
        assert headers == {"Authorization": f"Basic {expected}"}

    def test_from_vault_reads_json(self):
        vault = {
            "redmine:org1:i1": {
                "base_url": "https://r.example.com",
                "api_key": "vaultkey",
                "auth_mode": "api_key",
                "verify_ssl": True,
                "rate_limit_qps": 3.0,
                "closed_status_ids": [5, 6],
            }
        }
        client = RedmineClient.from_vault(vault, "redmine:org1:i1")
        assert client.base_url == "https://r.example.com"
        assert client._api_key == "vaultkey"
        assert client.rate_limit_qps == 3.0
        assert client.closed_status_ids == frozenset({5, 6})

    def test_from_vault_missing_base_url_raises(self):
        vault = {"ref": {"api_key": "k", "auth_mode": "api_key"}}
        with pytest.raises(ValueError):
            RedmineClient.from_vault(vault, "ref")

    def test_from_vault_missing_ref_raises(self):
        with pytest.raises(KeyError):
            RedmineClient.from_vault({}, "nonexistent")


# ---------------------------------------------------------------------------
# Task 2 — verify_identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifyIdentity:
    async def test_returns_user_id(self):
        session = _FakeSession([
            _FakeResp(200, {"user": {"id": 42, "login": "alice"}}),
        ])
        client = _client_with_session(session)
        uid = await client.verify_identity()
        assert uid == 42

    async def test_raises_auth_error_on_401(self):
        session = _FakeSession([_FakeResp(401, {})])
        client = _client_with_session(session)
        with pytest.raises(RedmineAuthError):
            await client.verify_identity()


# ---------------------------------------------------------------------------
# Task 3 — verify_ssl=False audit hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifySslAudit:
    async def test_audit_emitted_on_first_request(self):
        audit_calls: list[str] = []
        session = _FakeSession([
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(
            session, verify_ssl=False, audit_log=audit_calls.append
        )
        await client.verify_identity()
        assert len(audit_calls) == 1
        assert "verify_ssl=False" in audit_calls[0]
        assert client._ssl_audit_emitted is True

    async def test_audit_emitted_only_once(self):
        audit_calls: list[str] = []
        session = _FakeSession([
            _FakeResp(200, {"user": {"id": 1}}),
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(
            session, verify_ssl=False, audit_log=audit_calls.append
        )
        await client.verify_identity()
        await client.verify_identity()
        assert len(audit_calls) == 1

    async def test_no_audit_when_verify_ssl_true(self):
        audit_calls: list[str] = []
        session = _FakeSession([
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(
            session, verify_ssl=True, audit_log=audit_calls.append
        )
        await client.verify_identity()
        assert audit_calls == []


# ---------------------------------------------------------------------------
# Task 4 — iter_issues: keyset pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIterIssues:
    def _issue(self, iid: int, updated: str, status_closed: bool = True) -> dict:
        return {
            "id": iid,
            "project": {"id": 7, "name": "Ops"},
            "tracker": {"id": 1, "name": "Bug"},
            "status": {"id": 5, "name": "Resolved", "is_closed": status_closed},
            "subject": f"Issue {iid}",
            "description": "desc",
            "author": {"id": 1, "name": "Alice"},
            "created_on": "2025-09-01T00:00:00Z",
            "updated_on": updated,
        }

    async def test_yields_issues_in_window(self):
        data = {
            "issues": [
                self._issue(1, "2025-09-10T10:00:00Z"),
                self._issue(2, "2025-09-11T10:00:00Z"),
            ],
            "total_count": 2,
            "offset": 0,
            "limit": 100,
        }
        session = _FakeSession([_FakeResp(200, data)])
        client = _client_with_session(session)
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)
        until = datetime(2025, 9, 30, tzinfo=timezone.utc)
        issues = [i async for i in client.iter_issues(7, since, until)]
        assert len(issues) == 2
        assert issues[0].id == 1
        assert issues[1].id == 2

    async def test_keyset_dedup_skips_lower_id_same_timestamp(self):
        """Two issues share updated_on; lower id seen on page 2 is skipped."""
        ts = "2025-09-10T10:00:00Z"
        page1 = {
            "issues": [self._issue(10, ts), self._issue(11, ts)],
            "total_count": 3,
            "offset": 0,
            "limit": 2,
        }
        page2 = {
            "issues": [self._issue(10, ts)],  # duplicate from page shift
            "total_count": 3,
            "offset": 2,
            "limit": 2,
        }
        session = _FakeSession([_FakeResp(200, page1), _FakeResp(200, page2)])
        client = _client_with_session(session)
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)
        until = datetime(2025, 9, 30, tzinfo=timezone.utc)
        issues = [i async for i in client.iter_issues(7, since, until)]
        ids = [i.id for i in issues]
        # id 10 should appear only once
        assert ids.count(10) == 1

    async def test_stops_when_no_more_issues(self):
        data = {"issues": [], "total_count": 0, "offset": 0, "limit": 100}
        session = _FakeSession([_FakeResp(200, data)])
        client = _client_with_session(session)
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)
        until = datetime(2025, 9, 30, tzinfo=timezone.utc)
        issues = [i async for i in client.iter_issues(7, since, until)]
        assert issues == []


# ---------------------------------------------------------------------------
# Task 5 — fetch_memberships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchMemberships:
    async def test_returns_memberships(self):
        data = {
            "memberships": [
                {
                    "id": 1,
                    "project": {"id": 7, "name": "Ops"},
                    "user": {"id": 101, "name": "Alice"},
                    "roles": [{"id": 3, "name": "Developer"}],
                }
            ],
            "total_count": 1,
        }
        session = _FakeSession([_FakeResp(200, data)])
        client = _client_with_session(session)
        members = await client.fetch_memberships(7)
        assert len(members) == 1
        assert members[0].user_id == 101
        assert members[0].role_names == ["Developer"]

    async def test_raises_permission_error_on_403(self):
        session = _FakeSession([_FakeResp(403, {})])
        client = _client_with_session(session)
        with pytest.raises(PermissionError):
            await client.fetch_memberships(7)

    async def test_skips_group_memberships(self):
        """Memberships without user.id (groups) are silently skipped."""
        data = {
            "memberships": [
                {
                    "id": 1,
                    "project": {"id": 7},
                    "group": {"id": 99, "name": "Devs"},  # no 'user' key
                    "roles": [{"id": 3, "name": "Developer"}],
                }
            ],
            "total_count": 1,
        }
        session = _FakeSession([_FakeResp(200, data)])
        client = _client_with_session(session)
        members = await client.fetch_memberships(7)
        assert members == []


# ---------------------------------------------------------------------------
# Task 6 — iter_wiki_pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIterWikiPages:
    async def test_yields_pages_in_window(self):
        index = {
            "wiki_pages": [
                {"title": "Runbook", "updated_on": "2025-09-15T10:00:00Z"},
                {"title": "OldPage", "updated_on": "2024-01-01T00:00:00Z"},
            ]
        }
        page_data = {
            "wiki_page": {
                "title": "Runbook",
                "text": "# Runbook\nSteps here.",
                "created_on": "2025-01-01T00:00:00Z",
                "updated_on": "2025-09-15T10:00:00Z",
                "version": 3,
                "author": {"id": 101, "name": "Alice"},
            }
        }
        session = _FakeSession([
            _FakeResp(200, index),
            _FakeResp(200, page_data),
        ])
        client = _client_with_session(session)
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)
        until = datetime(2025, 9, 30, tzinfo=timezone.utc)
        pages = [p async for p in client.iter_wiki_pages(7, since, until)]
        assert len(pages) == 1
        assert pages[0].title == "Runbook"
        assert pages[0].text.startswith("# Runbook")

    async def test_skips_pages_outside_window(self):
        index = {
            "wiki_pages": [
                {"title": "Old", "updated_on": "2020-01-01T00:00:00Z"},
            ]
        }
        session = _FakeSession([_FakeResp(200, index)])
        client = _client_with_session(session)
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)
        until = datetime(2025, 9, 30, tzinfo=timezone.utc)
        pages = [p async for p in client.iter_wiki_pages(7, since, until)]
        assert pages == []


# ---------------------------------------------------------------------------
# Task 7 — Rate limiter (QPS pacing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_pacing_calls_sleep_between_requests(self):
        """With rate_limit_qps=1.0 two consecutive requests trigger a sleep."""
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)

        # Clock that always returns the same value → gap is always negative
        # so no sleeping needed, but we'll use fixed clock to force a gap.
        clock_vals = [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.5]
        clock_iter = iter(clock_vals)

        def fake_clock() -> float:
            try:
                return next(clock_iter)
            except StopIteration:
                return 1.0

        session = _FakeSession([
            _FakeResp(200, {"user": {"id": 1}}),
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(
            session,
            rate_limit_qps=1.0,
            _clock=fake_clock,
            _sleep=fake_sleep,
        )
        await client.verify_identity()
        await client.verify_identity()
        # At least one sleep was issued (rate-limit gap enforcement).
        assert len(slept) >= 1

    async def test_semaphore_is_1(self):
        """Client has a Semaphore(1) so at most one in-flight request."""
        client = _make_client()
        assert client._sem._value == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Task 8 — Backoff ladder + Retry-After
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBackoffLadder:
    async def test_429_with_retry_after_sleeps_exact_value(self):
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)

        session = _FakeSession([
            _FakeResp(429, {}, headers={"Retry-After": "17"}),
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(session, _sleep=fake_sleep)
        uid = await client.verify_identity()
        assert uid == 1
        assert slept[0] == 17.0

    async def test_429_without_retry_after_walks_backoff_ladder(self):
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)

        session = _FakeSession([
            _FakeResp(429, {}),
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(session, _sleep=fake_sleep)
        uid = await client.verify_identity()
        assert uid == 1
        assert slept[0] == _BACKOFF_SECONDS[0]

    async def test_5xx_walks_backoff_ladder(self):
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)

        session = _FakeSession([
            _FakeResp(503, {}),
            _FakeResp(200, {"user": {"id": 1}}),
        ])
        client = _client_with_session(session, _sleep=fake_sleep)
        uid = await client.verify_identity()
        assert uid == 1
        assert slept[0] == _BACKOFF_SECONDS[0]

    async def test_exhausted_retries_raises(self):
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)

        # Return 429 for all 4 attempts.
        session = _FakeSession([_FakeResp(429, {})] * 4)
        client = _client_with_session(session, _sleep=fake_sleep)
        with pytest.raises(RuntimeError, match="after"):
            await client.verify_identity()


# ---------------------------------------------------------------------------
# Task 9 — Legacy is_closed fallback
# ---------------------------------------------------------------------------


def _issue_with_is_closed(status_id: int, is_closed: bool | None) -> RedmineIssue:
    status = RedmineStatusRef(id=status_id, name="S", is_closed=is_closed)
    return RedmineIssue(
        id=1,
        subject="T",
        description="d",
        created_on=datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_on=datetime(2025, 1, 1, tzinfo=timezone.utc),
        project_id=1,
        status=status,
    )


class TestIsIssueClosed:
    def test_uses_is_closed_when_present(self):
        client = _make_client()
        issue = _issue_with_is_closed(5, True)
        assert client.is_issue_closed(issue) is True

    def test_is_closed_false_returns_false(self):
        client = _make_client()
        issue = _issue_with_is_closed(1, False)
        assert client.is_issue_closed(issue) is False

    def test_fallback_to_closed_status_ids(self):
        client = _make_client(closed_status_ids=[5, 6, 7])
        issue = _issue_with_is_closed(5, None)  # no is_closed field
        assert client.is_issue_closed(issue) is True

    def test_fallback_returns_false_when_not_in_ids(self):
        client = _make_client(closed_status_ids=[5, 6])
        issue = _issue_with_is_closed(1, None)
        assert client.is_issue_closed(issue) is False

    def test_returns_none_when_both_sources_absent(self):
        client = _make_client(closed_status_ids=[])
        issue = _issue_with_is_closed(1, None)
        result = client.is_issue_closed(issue)
        assert result is None

    def test_fallback_emits_warning_once(self, caplog):
        import logging
        client = _make_client(closed_status_ids=[5])
        issue1 = _issue_with_is_closed(5, None)
        issue2 = _issue_with_is_closed(5, None)
        with caplog.at_level(logging.WARNING):
            client.is_issue_closed(issue1)
            client.is_issue_closed(issue2)
        warnings = [r for r in caplog.records if "is_closed absent" in r.message]
        assert len(warnings) == 1, "should warn exactly once"

    def test_is_closed_when_using_explicit_ids_param(self):
        """Pass closed_status_ids as parameter override."""
        client = _make_client(closed_status_ids=[])
        issue = _issue_with_is_closed(99, None)
        # Pass explicit override
        result = client.is_issue_closed(issue, closed_status_ids=frozenset({99}))
        assert result is True


# ---------------------------------------------------------------------------
# Task 4/9 — attachment_eligible
# ---------------------------------------------------------------------------


class TestAttachmentEligible:
    def _att(self, mime: str, size: int):
        from breadmind.kb.backfill.adapters.redmine_types import RedmineAttachment
        from datetime import datetime, timezone
        return RedmineAttachment(
            id=1,
            filename="f",
            filesize=size,
            content_type=mime,
            content_url="https://x/1",
            created_on=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

    def test_text_plain_eligible(self):
        assert RedmineClient.attachment_eligible(self._att("text/plain", 100)) is True

    def test_text_markdown_eligible(self):
        assert RedmineClient.attachment_eligible(self._att("text/markdown", 100)) is True

    def test_application_json_eligible(self):
        assert RedmineClient.attachment_eligible(
            self._att("application/json", 100)) is True

    def test_image_png_not_eligible(self):
        assert RedmineClient.attachment_eligible(
            self._att("image/png", 100)) is False

    def test_too_large_not_eligible(self):
        assert RedmineClient.attachment_eligible(
            self._att("text/plain", 2_000_000)) is False

    def test_exactly_max_size_eligible(self):
        assert RedmineClient.attachment_eligible(
            self._att("text/plain", 1_048_576)) is True
