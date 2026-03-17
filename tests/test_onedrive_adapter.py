"""Tests for the OneDrive adapter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.personal.adapters.onedrive import (
    OneDriveAdapter,
    _graph_item_to_file,
)
from breadmind.personal.models import File
from breadmind.personal.oauth import OAuthCredentials, OAuthManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_item(
    item_id: str = "item-1",
    name: str = "report.pdf",
    mime_type: str = "application/pdf",
    size: int = 2048,
    web_url: str = "https://onedrive.live.com/item-1",
    parent_id: str | None = "parent-folder-1",
) -> dict:
    """Return a minimal OneDrive item resource."""
    item: dict = {
        "id": item_id,
        "name": name,
        "size": size,
        "webUrl": web_url,
        "file": {"mimeType": mime_type},
    }
    if parent_id is not None:
        item["parentReference"] = {"id": parent_id}
    return item


def _mock_oauth(authenticated: bool = True) -> OAuthManager:
    """Create an OAuthManager mock with valid credentials."""
    oauth = AsyncMock(spec=OAuthManager)
    if authenticated:
        creds = OAuthCredentials(
            provider="microsoft",
            access_token="test-token",
            token_type="Bearer",
        )
        oauth.get_credentials = AsyncMock(return_value=creds)
    else:
        oauth.get_credentials = AsyncMock(return_value=None)
    return oauth


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    """Create a mock aiohttp response as an async context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.raise_for_status = MagicMock()
    return resp


def _patch_session(adapter: OneDriveAdapter, response: AsyncMock) -> None:
    """Inject a mock session whose .request() returns *response*."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    session.closed = False
    adapter._session = session


# ---------------------------------------------------------------------------
# Tests -- mapping
# ---------------------------------------------------------------------------


def test_graph_item_to_file_mapping():
    item = _make_graph_item()
    result = _graph_item_to_file(item)

    assert isinstance(result, File)
    assert result.name == "report.pdf"
    assert result.path_or_url == "https://onedrive.live.com/item-1"
    assert result.mime_type == "application/pdf"
    assert result.size_bytes == 2048
    assert result.source == "onedrive"
    assert result.source_id == "item-1"
    assert result.parent_folder == "parent-folder-1"


def test_graph_item_to_file_missing_optional_fields():
    item = {"id": "f-2", "name": "empty.txt"}
    result = _graph_item_to_file(item)

    assert result.name == "empty.txt"
    assert result.path_or_url == ""
    assert result.mime_type == "application/octet-stream"
    assert result.size_bytes == 0
    assert result.parent_folder is None


# ---------------------------------------------------------------------------
# Tests -- adapter methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success():
    oauth = _mock_oauth(authenticated=True)
    adapter = OneDriveAdapter(oauth=oauth)
    drive_resp = _mock_response({"id": "drive-id", "driveType": "personal"})
    _patch_session(adapter, drive_resp)

    result = await adapter.authenticate({})

    assert result is True


@pytest.mark.asyncio
async def test_authenticate_no_credentials():
    oauth = _mock_oauth(authenticated=False)
    adapter = OneDriveAdapter(oauth=oauth)

    result = await adapter.authenticate({})

    assert result is False


@pytest.mark.asyncio
async def test_list_items():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)
    items_resp = _mock_response({"value": [_make_graph_item()]})
    _patch_session(adapter, items_resp)

    files = await adapter.list_items()

    assert len(files) == 1
    assert isinstance(files[0], File)
    assert files[0].name == "report.pdf"
    assert files[0].source == "onedrive"

    session = adapter._session
    session.request.assert_called_once()
    call_args = session.request.call_args
    assert call_args[0][0] == "GET"
    assert "/me/drive/root/children" in call_args[0][1]


@pytest.mark.asyncio
async def test_list_items_with_search_filter():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)
    items_resp = _mock_response({"value": [_make_graph_item()]})
    _patch_session(adapter, items_resp)

    files = await adapter.list_items(filters={"name_contains": "report"})

    assert len(files) == 1
    session = adapter._session
    call_args = session.request.call_args
    assert "search" in call_args[0][1]
    assert "report" in call_args[0][1]


@pytest.mark.asyncio
async def test_create_item():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)
    created_resp = _mock_response({"id": "new-item-id"})
    _patch_session(adapter, created_resp)

    entity = File(
        id="local-1",
        name="notes.txt",
        path_or_url="",
        mime_type="text/plain",
        parent_folder="folder-1",
    )
    item_id = await adapter.create_item(entity)

    assert item_id == "new-item-id"
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "POST"
    assert "/me/drive/items/folder-1/children" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["name"] == "notes.txt"


@pytest.mark.asyncio
async def test_update_item():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)
    update_resp = _mock_response({"id": "item-1", "name": "renamed.pdf"})
    _patch_session(adapter, update_resp)

    result = await adapter.update_item("item-1", {"name": "renamed.pdf"})

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "PATCH"
    assert "/me/drive/items/item-1" in call_args[0][1]
    assert call_args[1]["json"]["name"] == "renamed.pdf"


@pytest.mark.asyncio
async def test_update_item_empty_changes():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)

    result = await adapter.update_item("item-1", {})

    assert result is False


@pytest.mark.asyncio
async def test_sync():
    oauth = _mock_oauth()
    adapter = OneDriveAdapter(oauth=oauth)
    items_resp = _mock_response({
        "value": [
            _make_graph_item(item_id="f-1"),
            _make_graph_item(item_id="f-2"),
        ]
    })
    _patch_session(adapter, items_resp)

    result = await adapter.sync()

    assert "f-1" in result.created
    assert "f-2" in result.created
    assert result.errors == []
