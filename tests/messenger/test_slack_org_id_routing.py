"""T8 — Slack tenant_native_id propagation + router lookup → CoreAgent.org_id.

Covers:
  - SlackGateway extracts ``team`` (or ``team_id``) into IncomingMessage.tenant_native_id
  - dispatch_to_agent helper resolves org_id via _lookup_org_id_by_slack_team
  - miss path passes org_id=None and warns once (process-level dedupe)
  - _lookup_org_id_by_slack_team emits hit/miss metrics
  - clear_org_lookup_cache() resets the warned-team set
  - non-Slack platforms skip the lookup entirely
"""
from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.memory import runtime as runtime_mod
from breadmind.memory.runtime import (
    _lookup_org_id_by_slack_team,
    clear_org_lookup_cache,
)
from breadmind.messenger.org_routing import dispatch_to_agent
from breadmind.messenger.router import IncomingMessage
from breadmind.messenger.slack import SlackGateway


# ---------------------------------------------------------------------------
# Autouse fixture: clear the lookup cache + warned-set between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_state():
    clear_org_lookup_cache()
    yield
    clear_org_lookup_cache()


def _make_db(row):
    """Build a mock db whose acquire() is an async context manager returning conn."""
    conn = AsyncMock()
    conn.fetchrow.return_value = row
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = None
    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)
    return db, conn


# ---------------------------------------------------------------------------
# Family 1: SlackGateway sets tenant_native_id from message dict
# ---------------------------------------------------------------------------

def test_slack_gateway_build_msg_sets_tenant_native_id_from_team():
    """SlackGateway._build_msg copies the slack-bolt event's ``team`` field
    into IncomingMessage.tenant_native_id."""
    gw = SlackGateway(bot_token="xoxb-test")
    msg = gw._build_msg({
        "text": "hello",
        "user": "U_ALICE",
        "channel": "C1",
        "team": "T01ABC",
    })
    assert msg.text == "hello"
    assert msg.user_id == "U_ALICE"
    assert msg.channel_id == "C1"
    assert msg.platform == "slack"
    assert msg.tenant_native_id == "T01ABC"


def test_slack_gateway_build_msg_falls_back_to_team_id():
    """If only ``team_id`` is present (older payload variant), it is used."""
    gw = SlackGateway(bot_token="xoxb-test")
    msg = gw._build_msg({
        "text": "hi",
        "user": "U",
        "channel": "C",
        "team_id": "T02DEF",
    })
    assert msg.tenant_native_id == "T02DEF"


def test_slack_gateway_build_msg_none_when_team_missing():
    """No team key → tenant_native_id is None (NOT empty string)."""
    gw = SlackGateway(bot_token="xoxb-test")
    msg = gw._build_msg({"text": "hi", "user": "U", "channel": "C"})
    assert msg.tenant_native_id is None


def test_slack_gateway_build_msg_empty_team_str_normalized_to_none():
    """An empty-string ``team`` value should become None (not ``""``)."""
    gw = SlackGateway(bot_token="xoxb-test")
    msg = gw._build_msg({"text": "hi", "user": "U", "channel": "C", "team": ""})
    assert msg.tenant_native_id is None


# ---------------------------------------------------------------------------
# Family 2: dispatch_to_agent helper
# ---------------------------------------------------------------------------

async def test_dispatch_to_agent_resolves_org_id_via_lookup():
    org_id = uuid.uuid4()
    db, conn = _make_db({"id": org_id})
    agent_handle = AsyncMock(return_value="reply")

    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id="T01ABC",
    )

    result = await dispatch_to_agent(msg, db, agent_handle)

    assert result == "reply"
    agent_handle.assert_awaited_once_with(
        "hi", user="U", channel="C", org_id=org_id,
    )
    conn.fetchrow.assert_awaited_once()


async def test_dispatch_to_agent_miss_passes_none_and_warns_once(caplog):
    """DB returns no row → org_id=None passed to agent + 1 WARN log.
    Calling helper a second time with same team_id does NOT re-warn."""
    db, _ = _make_db(None)
    agent_handle = AsyncMock(return_value=None)

    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id="T_UNKNOWN",
    )

    with caplog.at_level(logging.WARNING, logger="breadmind.memory.runtime"):
        await dispatch_to_agent(msg, db, agent_handle)
        await dispatch_to_agent(msg, db, agent_handle)

    # Both calls forwarded org_id=None
    assert agent_handle.await_count == 2
    for call in agent_handle.await_args_list:
        assert call.kwargs["org_id"] is None

    warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "T_UNKNOWN" in r.getMessage()
    ]
    assert len(warns) == 1, f"expected exactly 1 warn, got {len(warns)}: {warns}"


async def test_dispatch_to_agent_no_db_passes_none_no_lookup():
    """db=None → no lookup, no warn, org_id=None forwarded."""
    agent_handle = AsyncMock(return_value=None)
    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id="T01ABC",
    )

    await dispatch_to_agent(msg, None, agent_handle)

    agent_handle.assert_awaited_once_with("hi", user="U", channel="C", org_id=None)


async def test_dispatch_to_agent_no_tenant_native_id_skips_lookup():
    """Slack message without tenant_native_id → no lookup, org_id=None."""
    db, conn = _make_db({"id": uuid.uuid4()})
    agent_handle = AsyncMock(return_value=None)
    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id=None,
    )

    await dispatch_to_agent(msg, db, agent_handle)

    agent_handle.assert_awaited_once_with("hi", user="U", channel="C", org_id=None)
    conn.fetchrow.assert_not_awaited()


async def test_dispatch_to_agent_non_slack_platform_skips_lookup():
    """Non-Slack platforms never trigger the Slack-team lookup."""
    db, conn = _make_db({"id": uuid.uuid4()})
    agent_handle = AsyncMock(return_value=None)
    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="discord", tenant_native_id="GUILD_123",
    )

    await dispatch_to_agent(msg, db, agent_handle)

    agent_handle.assert_awaited_once_with("hi", user="U", channel="C", org_id=None)
    # db.acquire never called for non-slack
    assert not db.acquire.called


# ---------------------------------------------------------------------------
# Family 3: _lookup_org_id_by_slack_team metric emission
# ---------------------------------------------------------------------------

def _read_counter(metric, **labels):
    """Read a labelled prometheus counter's current value."""
    try:
        return metric.labels(**labels)._value.get()
    except AttributeError:
        # _NoopMetric — no counter to read
        return None


async def test_lookup_emits_hit_metric():
    from breadmind.memory.metrics import org_id_lookup_total

    org_id = uuid.uuid4()
    db, _ = _make_db({"id": org_id})

    before = _read_counter(org_id_lookup_total, outcome="hit")
    if before is None:
        pytest.skip("prometheus_client not installed")

    await _lookup_org_id_by_slack_team("T_HIT", db)
    after = _read_counter(org_id_lookup_total, outcome="hit")
    assert after == before + 1


async def test_lookup_emits_miss_metric():
    from breadmind.memory.metrics import org_id_lookup_total

    db, _ = _make_db(None)

    before = _read_counter(org_id_lookup_total, outcome="miss")
    if before is None:
        pytest.skip("prometheus_client not installed")

    await _lookup_org_id_by_slack_team("T_MISS_METRIC", db)
    after = _read_counter(org_id_lookup_total, outcome="miss")
    assert after == before + 1


# ---------------------------------------------------------------------------
# Family 4: clear_org_lookup_cache also resets warned-set
#   (defined further below — see test_clear_org_lookup_cache_resets_warned_set)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Family 5: _route closure (via _make_route_handler) swallows exceptions
# ---------------------------------------------------------------------------


async def test_route_handler_swallows_dispatch_exception_and_logs(caplog):
    """When dispatch_to_agent raises, the router handler logs at ERROR
    and returns ``None`` so the gateway loop is not killed."""
    from breadmind.core.bootstrap import _make_route_handler

    failing_agent = AsyncMock(side_effect=RuntimeError("boom"))
    db, _ = _make_db({"id": uuid.uuid4()})

    handler = _make_route_handler(db, failing_agent)
    msg = IncomingMessage(
        text="hi", user_id="U_ALICE", channel_id="C",
        platform="slack", tenant_native_id="T01ABC",
    )

    with caplog.at_level(logging.ERROR, logger="breadmind.core.bootstrap"):
        result = await handler(msg)

    assert result is None
    errors = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "messenger dispatch failed" in r.getMessage()
    ]
    assert len(errors) == 1
    # Ensure the exception traceback is attached (logger.exception path).
    assert errors[0].exc_info is not None


async def test_route_handler_via_router_returns_none_on_failure():
    """Wired through MessageRouter.handle_message: router returns None
    instead of propagating the exception up to the gateway."""
    from breadmind.core.bootstrap import _make_route_handler
    from breadmind.messenger.router import MessageRouter

    failing_agent = AsyncMock(side_effect=RuntimeError("boom"))
    db, _ = _make_db({"id": uuid.uuid4()})

    router = MessageRouter()
    router.set_message_handler(_make_route_handler(db, failing_agent))

    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id="T01ABC",
    )

    # Must not raise.
    result = await router.handle_message(msg)
    assert result is None


# ---------------------------------------------------------------------------
# Family 6: SlackEnhancedGateway._build_incoming sets tenant_native_id
# ---------------------------------------------------------------------------


def test_slack_enhanced_build_incoming_sets_tenant_native_id_from_team():
    from breadmind.messenger.slack_enhanced import SlackEnhancedGateway

    gw = SlackEnhancedGateway(bot_token="xoxb-test", bot_user_id="UBOT")
    msg = gw._build_incoming({
        "text": "<@UBOT> hello",
        "user": "U_ALICE",
        "channel": "C1",
        "team": "T01ABC",
    })
    assert msg.platform == "slack"
    assert msg.user_id == "U_ALICE"
    assert msg.channel_id == "C1"
    assert msg.text == "hello"  # mention stripped
    assert msg.tenant_native_id == "T01ABC"


def test_slack_enhanced_build_incoming_falls_back_to_team_id():
    from breadmind.messenger.slack_enhanced import SlackEnhancedGateway

    gw = SlackEnhancedGateway(bot_token="xoxb-test", bot_user_id="UBOT")
    msg = gw._build_incoming({
        "text": "hi",
        "user": "U",
        "channel": "C",
        "team_id": "T02DEF",
    })
    assert msg.tenant_native_id == "T02DEF"


def test_slack_enhanced_build_incoming_none_when_team_missing():
    from breadmind.messenger.slack_enhanced import SlackEnhancedGateway

    gw = SlackEnhancedGateway(bot_token="xoxb-test", bot_user_id="UBOT")
    msg = gw._build_incoming({"text": "hi", "user": "U", "channel": "C"})
    assert msg.tenant_native_id is None


def test_slack_enhanced_build_incoming_empty_team_normalized_to_none():
    from breadmind.messenger.slack_enhanced import SlackEnhancedGateway

    gw = SlackEnhancedGateway(bot_token="xoxb-test", bot_user_id="UBOT")
    msg = gw._build_incoming({
        "text": "hi", "user": "U", "channel": "C", "team": "",
    })
    assert msg.tenant_native_id is None


# ---------------------------------------------------------------------------
# Family 4: clear_org_lookup_cache also resets warned-set
# ---------------------------------------------------------------------------


async def test_clear_org_lookup_cache_resets_warned_set(caplog):
    """After clear_org_lookup_cache(), a previously-warned team_id WILL warn again."""
    db, _ = _make_db(None)
    agent_handle = AsyncMock(return_value=None)
    msg = IncomingMessage(
        text="hi", user_id="U", channel_id="C",
        platform="slack", tenant_native_id="T_RESET",
    )

    # First miss — warn emitted
    with caplog.at_level(logging.WARNING, logger="breadmind.memory.runtime"):
        await dispatch_to_agent(msg, db, agent_handle)
    first_warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "T_RESET" in r.getMessage()
    ]
    assert len(first_warns) == 1

    # Clear both cache and warned-set
    clear_org_lookup_cache()
    assert "T_RESET" not in runtime_mod._warned_team_ids

    # Second miss after clear — should warn again
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="breadmind.memory.runtime"):
        await dispatch_to_agent(msg, db, agent_handle)
    second_warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "T_RESET" in r.getMessage()
    ]
    assert len(second_warns) == 1
