"""Tests for ``breadmind.connectors.slack_web.SlackWebSession``.

The session wraps slack-sdk's :class:`AsyncWebClient` so that
``SlackBackfillAdapter`` (which calls ``await session.call(method, **params)``
and reads ``payload["ok"] / payload["_status"] / payload["_retry_after"]``)
can run against the real Slack web API in production.

Tests inject a fake client via the ``client_factory`` constructor seam so
no HTTP traffic is generated and slack-sdk's transport stays out of unit
tests entirely.
"""
from __future__ import annotations

from typing import Any

import pytest

from breadmind.connectors.slack_web import SlackWebSession


class _FakeVault:
    def __init__(self, token: str | None) -> None:
        self._token = token
        self.calls: list[str] = []

    async def retrieve(self, ref: str) -> str | None:
        self.calls.append(ref)
        return self._token


class _FakeSlackError(Exception):
    """Minimal stand-in for ``slack_sdk.errors.SlackApiError``.

    Carries a ``response`` attribute exposing ``status_code``, ``headers``
    and ``data`` so the SlackWebSession's exception handler can read the
    same shape it would in production.
    """

    def __init__(self, response: "_FakeResponse") -> None:
        super().__init__(response.data.get("error", "slack_api_error"))
        self.response = response


class _FakeResponse:
    def __init__(
        self, data: dict[str, Any], *, status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.data = data
        self.status_code = status_code
        self.headers = headers or {}


class _FakeClient:
    """Records api_call invocations and returns scripted responses."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def api_call(self, method: str, *, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, dict(params or {})))
        if not self._responses:
            raise AssertionError(f"unexpected api_call: {method}")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _factory_returning(client: _FakeClient):
    def _make(token: str) -> _FakeClient:
        client.token = token  # type: ignore[attr-defined]
        return client
    return _make


# ---------------------------------------------------------------------------
# 1. Basic routing: token loaded from vault, method+params forwarded, dict
#    returned with the slack payload.
# ---------------------------------------------------------------------------


async def test_call_loads_token_and_forwards_method_with_params() -> None:
    vault = _FakeVault("xoxb-prod-token")
    fake_client = _FakeClient(
        [_FakeResponse({"ok": True, "team_id": "T_PROD"})]
    )
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:abc",
        client_factory=_factory_returning(fake_client),
    )

    result = await session.call("auth.test")

    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["team_id"] == "T_PROD"
    assert vault.calls == ["slack:org:abc"]
    assert fake_client.calls == [("auth.test", {})]
    assert fake_client.token == "xoxb-prod-token"  # type: ignore[attr-defined]


async def test_call_passes_kwargs_as_slack_params() -> None:
    vault = _FakeVault("xoxb-prod")
    fake_client = _FakeClient([
        _FakeResponse({"ok": True, "channel": {"id": "C1", "is_archived": False}}),
    ])
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:x",
        client_factory=_factory_returning(fake_client),
    )

    await session.call("conversations.info", channel="C1")

    assert fake_client.calls == [("conversations.info", {"channel": "C1"})]


# ---------------------------------------------------------------------------
# 2. Token-missing path: clear RuntimeError, vault is consulted.
# ---------------------------------------------------------------------------


async def test_call_raises_when_vault_returns_no_token() -> None:
    vault = _FakeVault(None)
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:missing",
        client_factory=_factory_returning(_FakeClient([])),
    )

    with pytest.raises(RuntimeError, match="slack:org:missing"):
        await session.call("auth.test")


# ---------------------------------------------------------------------------
# 3. Caching: token + client are loaded only on the first call.
# ---------------------------------------------------------------------------


async def test_client_and_token_are_cached_across_calls() -> None:
    vault = _FakeVault("xoxb-cached")
    fake_client = _FakeClient([
        _FakeResponse({"ok": True}),
        _FakeResponse({"ok": True, "members": [], "response_metadata": {}}),
    ])
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:cache",
        client_factory=_factory_returning(fake_client),
    )

    await session.call("auth.test")
    await session.call("conversations.members", channel="C1")

    assert vault.calls == ["slack:org:cache"]  # exactly one vault retrieve
    assert len(fake_client.calls) == 2


# ---------------------------------------------------------------------------
# 4. 429 mapping: SlackApiError with 429 → dict with ``_status`` and
#    ``_retry_after`` so the adapter's _call_with_retry loop sleeps the
#    advertised duration.
# ---------------------------------------------------------------------------


async def test_429_response_is_mapped_to_status_and_retry_after() -> None:
    vault = _FakeVault("xoxb-rl")
    rate_limited = _FakeSlackError(
        _FakeResponse(
            {"ok": False, "error": "ratelimited"},
            status_code=429,
            headers={"Retry-After": "17"},
        )
    )
    fake_client = _FakeClient([rate_limited])
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:rl",
        client_factory=_factory_returning(fake_client),
        slack_api_error=_FakeSlackError,
    )

    result = await session.call("conversations.history", channel="C1")

    assert result["ok"] is False
    assert result["error"] == "ratelimited"
    assert result["_status"] == 429
    assert result["_retry_after"] == 17


# ---------------------------------------------------------------------------
# 5. Non-429 SlackApiError: payload data is passed through (e.g.
#    ``ok=False, error=channel_not_found``) so the adapter sees the same
#    shape it would on a successful response.
# ---------------------------------------------------------------------------


async def test_non_rate_limit_slack_error_passes_payload_through() -> None:
    vault = _FakeVault("xoxb-err")
    api_err = _FakeSlackError(
        _FakeResponse(
            {"ok": False, "error": "channel_not_found"}, status_code=404,
        )
    )
    fake_client = _FakeClient([api_err])
    session = SlackWebSession(
        vault=vault, credentials_ref="slack:org:err",
        client_factory=_factory_returning(fake_client),
        slack_api_error=_FakeSlackError,
    )

    result = await session.call("conversations.info", channel="C_DEAD")

    assert result["ok"] is False
    assert result["error"] == "channel_not_found"
    assert "_status" not in result or result["_status"] == 404
