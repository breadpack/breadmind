"""Tests for OutgoingWebhookDispatcher."""
from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from breadmind.core.outgoing_webhook import (
    OutgoingWebhookDispatcher,
    WebhookTarget,
    sign_payload,
)


# ── Helpers ───────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status: int = 200, body: str = "ok"):
        self.status = status
        self._body = body

    async def text(self):
        return self._body


class FakeSession:
    """Mimics aiohttp.ClientSession as an async context manager with .post()."""

    def __init__(self, response_factory=None):
        self.calls: list[dict] = []
        self._response_factory = response_factory or (lambda *a, **kw: FakeResponse())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    @asynccontextmanager
    async def post(self, url, *, data=None, headers=None):
        self.calls.append({"url": url, "data": data, "headers": headers})
        yield self._response_factory(url, data=data, headers=headers)


def _patch_session(fake_session):
    return patch(
        "breadmind.core.outgoing_webhook.aiohttp.ClientSession",
        return_value=fake_session,
    )


# ── Tests ─────────────────────────────────────────────────────────────


async def test_dispatch_success():
    target = WebhookTarget(url="https://example.com/hook", events=["test_event"])
    dispatcher = OutgoingWebhookDispatcher(targets=[target])
    session = FakeSession()

    with _patch_session(session):
        await dispatcher.dispatch("test_event", {"key": "value"})

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["success"] is True
    assert log[0]["url"] == "https://example.com/hook"
    assert len(session.calls) == 1


async def test_dispatch_with_signature():
    secret = "my-secret"
    target = WebhookTarget(url="https://example.com/hook", events=["ev"], secret=secret)
    dispatcher = OutgoingWebhookDispatcher(targets=[target])
    session = FakeSession()

    with _patch_session(session):
        await dispatcher.dispatch("ev", {"x": 1})

    assert len(session.calls) == 1
    headers = session.calls[0]["headers"]
    assert "X-Webhook-Signature" in headers

    # Verify the signature is correct
    log = dispatcher.get_delivery_log()
    delivery_id = log[0]["delivery_id"]
    payload_json = json.dumps({
        "event_type": "ev",
        "timestamp": log[0]["timestamp"],
        "data": {"x": 1},
        "delivery_id": delivery_id,
    })
    expected_sig = hmac_mod.new(secret.encode(), payload_json.encode(), hashlib.sha256).hexdigest()
    assert headers["X-Webhook-Signature"] == expected_sig


async def test_dispatch_retry_on_failure():
    target = WebhookTarget(url="https://example.com/hook", events=["ev"], retry_count=3)
    dispatcher = OutgoingWebhookDispatcher(targets=[target])

    call_count = 0

    def make_fail_response(*a, **kw):
        nonlocal call_count
        call_count += 1
        return FakeResponse(status=500, body="error")

    session = FakeSession(response_factory=make_fail_response)

    with (
        _patch_session(session),
        patch("breadmind.core.outgoing_webhook.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await dispatcher.dispatch("ev", {})

    assert call_count == 3
    assert mock_sleep.await_count == 2  # 2 sleeps between 3 attempts

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["success"] is False


async def test_dispatch_skip_disabled():
    enabled = WebhookTarget(url="https://a.com", events=["ev"], enabled=True)
    disabled = WebhookTarget(url="https://b.com", events=["ev"], enabled=False)
    dispatcher = OutgoingWebhookDispatcher(targets=[enabled, disabled])
    session = FakeSession()

    with _patch_session(session):
        await dispatcher.dispatch("ev", {})

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["url"] == "https://a.com"


async def test_event_filtering():
    t1 = WebhookTarget(url="https://a.com", events=["alpha"])
    t2 = WebhookTarget(url="https://b.com", events=["beta"])
    dispatcher = OutgoingWebhookDispatcher(targets=[t1, t2])
    session = FakeSession()

    with _patch_session(session):
        await dispatcher.dispatch("alpha", {})

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["url"] == "https://a.com"


async def test_add_remove_target():
    dispatcher = OutgoingWebhookDispatcher()
    t = WebhookTarget(url="https://a.com", events=["ev"])
    dispatcher.add_target(t)
    assert len(dispatcher._targets) == 1

    dispatcher.remove_target("https://a.com")
    assert len(dispatcher._targets) == 0


async def test_delivery_log():
    target = WebhookTarget(url="https://a.com", events=["ev"])
    dispatcher = OutgoingWebhookDispatcher(targets=[target])
    session = FakeSession()

    with _patch_session(session):
        for _ in range(5):
            await dispatcher.dispatch("ev", {})

    assert len(dispatcher.get_delivery_log()) == 5
    assert len(dispatcher.get_delivery_log(limit=3)) == 3


async def test_sign_payload():
    secret = "test-secret"
    payload = '{"event_type":"test","data":{}}'
    result = sign_payload(payload, secret)
    expected = hmac_mod.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert result == expected


async def test_dispatch_timeout():
    target = WebhookTarget(url="https://a.com", events=["ev"], retry_count=1)
    dispatcher = OutgoingWebhookDispatcher(targets=[target])

    def raise_timeout(*a, **kw):
        raise asyncio.TimeoutError("timed out")

    class TimeoutSession(FakeSession):
        @asynccontextmanager
        async def post(self, url, *, data=None, headers=None):
            raise asyncio.TimeoutError("timed out")
            yield  # noqa: F541 - needed for generator syntax

    session = TimeoutSession()

    with _patch_session(session):
        await dispatcher.dispatch("ev", {"key": "val"})

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["success"] is False
    assert "timed out" in log[0].get("error", "")


async def test_fire_and_forget():
    target = WebhookTarget(url="https://a.com", events=["ev"])
    dispatcher = OutgoingWebhookDispatcher(targets=[target])
    session = FakeSession()

    with _patch_session(session):
        dispatcher.dispatch_async("ev", {"x": 1})
        # Let the background task run
        await asyncio.sleep(0.1)

    log = dispatcher.get_delivery_log()
    assert len(log) == 1
    assert log[0]["success"] is True
