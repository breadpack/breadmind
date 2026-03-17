"""Tests for the Google Contacts adapter (People API)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.personal.adapters.google_contacts import (
    GoogleContactsAdapter,
    _contact_to_person,
    _person_to_contact,
)
from breadmind.personal.models import Contact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_person(
    resource_name: str = "people/c123",
    display_name: str = "Alice Kim",
    email: str | None = "alice@example.com",
    phone: str | None = "+82-10-1234-5678",
    organization: str | None = "BreadMind Corp",
    biography: str | None = None,
) -> dict:
    """Return a minimal Google People API person resource."""
    person: dict = {"resourceName": resource_name, "etag": "abc123"}
    if display_name:
        person["names"] = [{"displayName": display_name}]
    if email:
        person["emailAddresses"] = [{"value": email}]
    if phone:
        person["phoneNumbers"] = [{"value": phone}]
    if organization:
        person["organizations"] = [{"name": organization}]
    if biography:
        person["biographies"] = [{"value": biography}]
    return person


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    """Create a mock aiohttp response as an async context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.raise_for_status = MagicMock()
    return resp


def _patch_session(adapter: GoogleContactsAdapter, response: AsyncMock) -> None:
    """Inject a mock session whose .request() returns *response*."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    session.closed = False
    adapter._session = session


def _authed_adapter() -> GoogleContactsAdapter:
    adapter = GoogleContactsAdapter()
    adapter._access_token = "test-token"
    return adapter


# ---------------------------------------------------------------------------
# Unit tests for mapping functions
# ---------------------------------------------------------------------------


def test_person_to_contact_full():
    person = _make_person(biography="VIP client")
    contact = _person_to_contact(person)

    assert contact.name == "Alice Kim"
    assert contact.email == "alice@example.com"
    assert contact.phone == "+82-10-1234-5678"
    assert contact.organization == "BreadMind Corp"
    assert contact.notes == "VIP client"
    assert contact.platform_ids == {"google_contacts": "people/c123"}


def test_person_to_contact_minimal():
    person = {"resourceName": "people/c999"}
    contact = _person_to_contact(person)

    assert contact.name == ""
    assert contact.email is None
    assert contact.phone is None
    assert contact.organization is None
    assert contact.notes is None


def test_contact_to_person():
    contact = Contact(
        id="local-1",
        name="Bob Lee",
        email="bob@example.com",
        phone="+1-555-0100",
        organization="Acme Inc",
        notes="Friend",
    )
    person = _contact_to_person(contact)

    assert person["names"] == [{"givenName": "Bob Lee"}]
    assert person["emailAddresses"] == [{"value": "bob@example.com"}]
    assert person["phoneNumbers"] == [{"value": "+1-555-0100"}]
    assert person["organizations"] == [{"name": "Acme Inc"}]
    assert person["biographies"] == [{"value": "Friend"}]


# ---------------------------------------------------------------------------
# Adapter interface tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success():
    adapter = GoogleContactsAdapter()
    profile_resp = _mock_response({"resourceName": "people/me", "names": [{"displayName": "Me"}]})
    _patch_session(adapter, profile_resp)

    result = await adapter.authenticate({"access_token": "good-token"})

    assert result is True
    assert adapter._access_token == "good-token"


@pytest.mark.asyncio
async def test_authenticate_failure():
    adapter = GoogleContactsAdapter()
    fail_resp = _mock_response({}, status=401)
    fail_resp.raise_for_status = MagicMock(side_effect=Exception("Unauthorized"))
    _patch_session(adapter, fail_resp)

    result = await adapter.authenticate({"access_token": "bad-token"})

    assert result is False
    assert adapter._access_token is None


@pytest.mark.asyncio
async def test_list_items():
    adapter = _authed_adapter()
    person = _make_person()
    list_resp = _mock_response({"connections": [person]})
    _patch_session(adapter, list_resp)

    contacts = await adapter.list_items()

    assert len(contacts) == 1
    assert isinstance(contacts[0], Contact)
    assert contacts[0].name == "Alice Kim"
    assert contacts[0].email == "alice@example.com"

    session = adapter._session
    session.request.assert_called_once()
    call_args = session.request.call_args
    assert call_args[0][0] == "GET"
    assert "/people/me/connections" in call_args[0][1]


@pytest.mark.asyncio
async def test_get_item():
    adapter = _authed_adapter()
    person = _make_person(resource_name="people/c456", display_name="Charlie Park")
    get_resp = _mock_response(person)
    _patch_session(adapter, get_resp)

    contact = await adapter.get_item("people/c456")

    assert isinstance(contact, Contact)
    assert contact.name == "Charlie Park"
    assert contact.platform_ids["google_contacts"] == "people/c456"


@pytest.mark.asyncio
async def test_create_item():
    adapter = _authed_adapter()
    created_resp = _mock_response({"resourceName": "people/c789", "etag": "new"})
    _patch_session(adapter, created_resp)

    contact = Contact(id="local-1", name="Dana Yoon", email="dana@example.com")
    resource_name = await adapter.create_item(contact)

    assert resource_name == "people/c789"
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "POST"
    assert "/people:createContact" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["names"] == [{"givenName": "Dana Yoon"}]
    assert body["emailAddresses"] == [{"value": "dana@example.com"}]


@pytest.mark.asyncio
async def test_update_item():
    adapter = _authed_adapter()

    # First call: GET current person (for etag), second call: PATCH update.
    current_person = _make_person(resource_name="people/c123")
    get_resp = _mock_response(current_person)
    patch_resp = _mock_response({"resourceName": "people/c123"})

    session = AsyncMock()
    call_count = 0
    responses = [get_resp, patch_resp]

    def make_ctx(*args, **kwargs):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    session.request = MagicMock(side_effect=make_ctx)
    session.closed = False
    adapter._session = session

    result = await adapter.update_item("people/c123", {"name": "Alice Park", "email": "newalice@example.com"})

    assert result is True
    assert session.request.call_count == 2
    # Second call should be the PATCH
    patch_call = session.request.call_args_list[1]
    assert patch_call[0][0] == "PATCH"
    assert ":updateContact" in patch_call[0][1]


@pytest.mark.asyncio
async def test_delete_item():
    adapter = _authed_adapter()
    del_resp = _mock_response({}, status=204)
    _patch_session(adapter, del_resp)

    result = await adapter.delete_item("people/c123")

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "DELETE"
    assert "/people/c123:deleteContact" in call_args[0][1]


@pytest.mark.asyncio
async def test_sync():
    adapter = _authed_adapter()
    person = _make_person()
    sync_resp = _mock_response({"connections": [person]})
    _patch_session(adapter, sync_resp)

    result = await adapter.sync()

    assert len(result.created) == 1
    assert result.created[0] == "people/c123"
    assert result.errors == []


@pytest.mark.asyncio
async def test_domain_and_source():
    adapter = GoogleContactsAdapter()
    assert adapter.domain == "contact"
    assert adapter.source == "google_contacts"
