# tests/test_outlook_calendar_adapter.py
"""OutlookCalendarAdapter unit tests using mock OAuth and mock aiohttp."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.personal.adapters.outlook_calendar import OutlookCalendarAdapter
from breadmind.personal.models import Event


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_response(status=200, json_data=None):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    return resp


def _make_session(response):
    """Create a mock aiohttp.ClientSession with all HTTP methods."""
    session = AsyncMock()
    for method in ("get", "post", "patch", "put", "delete"):
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)
        setattr(session, method, MagicMock(return_value=cm))
    return session


def _session_ctx(session):
    """Wrap a mock session as an async context manager."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_oauth(has_creds: bool = True):
    """Create a mock OAuthManager returning credentials or None."""
    oauth = AsyncMock()
    if has_creds:
        creds = MagicMock()
        creds.access_token = "eyJ0eXAi.test-ms-token"
        oauth.get_credentials = AsyncMock(return_value=creds)
    else:
        oauth.get_credentials = AsyncMock(return_value=None)
    return oauth


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_GRAPH_EVENT = {
    "id": "AAMk123",
    "subject": "Team standup",
    "bodyPreview": "Daily sync meeting",
    "start": {"dateTime": "2026-03-17T09:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-03-17T09:30:00.0000000", "timeZone": "UTC"},
    "isAllDay": False,
    "location": {"displayName": "Conference Room A"},
    "attendees": [
        {"emailAddress": {"address": "alice@example.com", "name": "Alice"}, "type": "required"},
        {"emailAddress": {"address": "bob@example.com", "name": "Bob"}, "type": "required"},
    ],
    "reminderMinutesBeforeStart": 10,
}

SAMPLE_ALL_DAY_EVENT = {
    "id": "AAMk456",
    "subject": "Company holiday",
    "bodyPreview": "",
    "start": {"dateTime": "2026-03-20T00:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-03-21T00:00:00.0000000", "timeZone": "UTC"},
    "isAllDay": True,
    "location": {"displayName": ""},
    "attendees": [],
    "reminderMinutesBeforeStart": 15,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    return OutlookCalendarAdapter(oauth_manager=_mock_oauth())


@pytest.fixture
def adapter_no_creds():
    return OutlookCalendarAdapter(oauth_manager=_mock_oauth(has_creds=False))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authenticate_with_credentials(adapter):
    result = await adapter.authenticate({})
    assert result is True
    assert adapter.domain == "event"
    assert adapter.source == "outlook"


@pytest.mark.asyncio
async def test_authenticate_without_credentials(adapter_no_creds):
    result = await adapter_no_creds.authenticate({})
    assert result is False


@pytest.mark.asyncio
async def test_list_items(adapter):
    resp = _make_response(json_data={"value": [SAMPLE_GRAPH_EVENT, SAMPLE_ALL_DAY_EVENT]})
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        events = await adapter.list_items()

    assert len(events) == 2
    assert events[0].title == "Team standup"
    assert events[0].source == "outlook"
    assert events[1].title == "Company holiday"
    assert events[1].all_day is True


@pytest.mark.asyncio
async def test_list_items_no_credentials(adapter_no_creds):
    events = await adapter_no_creds.list_items()
    assert events == []


@pytest.mark.asyncio
async def test_list_items_with_time_filter(adapter):
    resp = _make_response(json_data={"value": []})
    session = _make_session(resp)

    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 31, tzinfo=timezone.utc)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        await adapter.list_items(filters={"start_after": start, "start_before": end})

    call_args = session.get.call_args
    params = call_args[1].get("params") or call_args.kwargs.get("params", {})
    assert "$filter" in params


@pytest.mark.asyncio
async def test_create_item(adapter):
    resp = _make_response(status=200, json_data={"id": "AAMk789"})
    session = _make_session(resp)

    event = Event(
        id="",
        title="New meeting",
        description="Discuss roadmap",
        start_at=datetime(2026, 3, 18, 14, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 3, 18, 15, 0, tzinfo=timezone.utc),
        location="Room B",
        attendees=["carol@example.com"],
    )

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result_id = await adapter.create_item(event)

    assert result_id == "AAMk789"
    call_args = session.post.call_args
    payload = call_args[1].get("json") or call_args.kwargs.get("json", {})
    assert payload["subject"] == "New meeting"
    assert payload["body"] == {"contentType": "text", "content": "Discuss roadmap"}
    assert payload["location"] == {"displayName": "Room B"}
    assert payload["attendees"] == [
        {"emailAddress": {"address": "carol@example.com"}, "type": "required"}
    ]


@pytest.mark.asyncio
async def test_create_item_no_credentials(adapter_no_creds):
    event = Event(
        id="",
        title="Blocked",
        start_at=datetime(2026, 3, 18, 14, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 3, 18, 15, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter_no_creds.create_item(event)


@pytest.mark.asyncio
async def test_update_item(adapter):
    resp = _make_response(status=200)
    session = _make_session(resp)

    new_start = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.update_item(
            "AAMk123",
            {"title": "Updated standup", "start_at": new_start, "description": "Changed"},
        )

    assert result is True
    call_args = session.patch.call_args
    payload = call_args[1].get("json") or call_args.kwargs.get("json", {})
    assert payload["subject"] == "Updated standup"
    assert payload["body"] == {"contentType": "text", "content": "Changed"}
    assert "start" in payload


@pytest.mark.asyncio
async def test_update_item_empty_changes(adapter):
    result = await adapter.update_item("AAMk123", {})
    assert result is False


@pytest.mark.asyncio
async def test_delete_item(adapter):
    resp = _make_response(status=204)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.delete_item("AAMk123")

    assert result is True


@pytest.mark.asyncio
async def test_delete_item_not_found(adapter):
    resp = _make_response(status=404)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.delete_item("nonexistent")

    assert result is False


@pytest.mark.asyncio
async def test_get_item_found(adapter):
    resp = _make_response(status=200, json_data=SAMPLE_GRAPH_EVENT)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        event = await adapter.get_item("AAMk123")

    assert event is not None
    assert event.title == "Team standup"
    assert event.source_id == "AAMk123"


@pytest.mark.asyncio
async def test_get_item_not_found(adapter):
    resp = _make_response(status=404)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        event = await adapter.get_item("missing")

    assert event is None


@pytest.mark.asyncio
async def test_to_event_mapping():
    adapter = OutlookCalendarAdapter(oauth_manager=_mock_oauth())
    event = adapter._to_event(SAMPLE_GRAPH_EVENT)

    assert event.id == "AAMk123"
    assert event.title == "Team standup"
    assert event.description == "Daily sync meeting"
    assert event.location == "Conference Room A"
    assert event.all_day is False
    assert event.attendees == ["alice@example.com", "bob@example.com"]
    assert event.reminder_minutes == [10]
    assert event.source == "outlook"
    assert event.source_id == "AAMk123"
    assert event.start_at.hour == 9
    assert event.start_at.tzinfo is not None
    assert event.end_at.minute == 30


@pytest.mark.asyncio
async def test_to_event_all_day_mapping():
    adapter = OutlookCalendarAdapter(oauth_manager=_mock_oauth())
    event = adapter._to_event(SAMPLE_ALL_DAY_EVENT)

    assert event.all_day is True
    assert event.start_at.year == 2026
    assert event.start_at.month == 3
    assert event.start_at.day == 20
    assert event.location is None  # empty displayName -> None
    assert event.attendees == []
    assert event.reminder_minutes == [15]


@pytest.mark.asyncio
async def test_sync(adapter):
    resp = _make_response(json_data={"value": [SAMPLE_GRAPH_EVENT]})
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.sync()

    assert result.created == ["AAMk123"]
    assert result.updated == []
    assert result.deleted == []
    assert result.errors == []
