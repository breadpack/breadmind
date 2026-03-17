"""Tests for the Google Drive adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.personal.adapters.google_drive import (
    GoogleDriveAdapter,
    _build_query,
    _drive_file_to_file,
)
from breadmind.personal.models import File
from breadmind.personal.oauth import OAuthCredentials, OAuthManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_drive_file(
    file_id: str = "file-1",
    name: str = "report.pdf",
    mime_type: str = "application/pdf",
    size: str = "2048",
    web_view_link: str = "https://drive.google.com/file/d/file-1/view",
    parents: list[str] | None = None,
) -> dict:
    """Return a minimal Google Drive file resource."""
    item: dict = {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "size": size,
        "webViewLink": web_view_link,
    }
    if parents is not None:
        item["parents"] = parents
    return item


def _mock_oauth(authenticated: bool = True) -> OAuthManager:
    """Create an OAuthManager mock with valid credentials."""
    oauth = AsyncMock(spec=OAuthManager)
    if authenticated:
        creds = OAuthCredentials(
            provider="google",
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


def _patch_session(adapter: GoogleDriveAdapter, response: AsyncMock) -> None:
    """Inject a mock session whose .request() returns *response*."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    session.closed = False
    adapter._session = session


# ---------------------------------------------------------------------------
# Tests — mapping
# ---------------------------------------------------------------------------


def test_drive_file_to_file_mapping():
    item = _make_drive_file(parents=["folder-1"])
    result = _drive_file_to_file(item)

    assert isinstance(result, File)
    assert result.name == "report.pdf"
    assert result.path_or_url == "https://drive.google.com/file/d/file-1/view"
    assert result.mime_type == "application/pdf"
    assert result.size_bytes == 2048
    assert result.source == "google_drive"
    assert result.source_id == "file-1"
    assert result.parent_folder == "folder-1"


def test_drive_file_to_file_missing_optional_fields():
    item = {"id": "f-2", "name": "empty.txt"}
    result = _drive_file_to_file(item)

    assert result.name == "empty.txt"
    assert result.path_or_url == ""
    assert result.mime_type == "application/octet-stream"
    assert result.size_bytes == 0
    assert result.parent_folder is None


# ---------------------------------------------------------------------------
# Tests — query builder
# ---------------------------------------------------------------------------


def test_build_query_name_contains():
    q = _build_query({"name_contains": "budget"})
    assert "name contains 'budget'" in q
    assert "trashed = false" in q


def test_build_query_multiple_filters():
    q = _build_query({
        "name_contains": "report",
        "mime_type": "application/pdf",
        "parent": "folder-abc",
    })
    assert "name contains 'report'" in q
    assert "mimeType = 'application/pdf'" in q
    assert "'folder-abc' in parents" in q
    assert "trashed = false" in q


# ---------------------------------------------------------------------------
# Tests — adapter methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success():
    oauth = _mock_oauth(authenticated=True)
    adapter = GoogleDriveAdapter(oauth=oauth)
    about_resp = _mock_response({"user": {"displayName": "Test"}})
    _patch_session(adapter, about_resp)

    result = await adapter.authenticate({})

    assert result is True


@pytest.mark.asyncio
async def test_authenticate_no_credentials():
    oauth = _mock_oauth(authenticated=False)
    adapter = GoogleDriveAdapter(oauth=oauth)

    result = await adapter.authenticate({})

    assert result is False


@pytest.mark.asyncio
async def test_list_items():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    files_resp = _mock_response({"files": [_make_drive_file()]})
    _patch_session(adapter, files_resp)

    files = await adapter.list_items()

    assert len(files) == 1
    assert isinstance(files[0], File)
    assert files[0].name == "report.pdf"
    assert files[0].source == "google_drive"

    session = adapter._session
    session.request.assert_called_once()
    call_args = session.request.call_args
    assert call_args[0][0] == "GET"
    assert "/files" in call_args[0][1]


@pytest.mark.asyncio
async def test_list_items_with_filters():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    files_resp = _mock_response({"files": [_make_drive_file()]})
    _patch_session(adapter, files_resp)

    files = await adapter.list_items(filters={"name_contains": "report"})

    assert len(files) == 1
    session = adapter._session
    call_kwargs = session.request.call_args[1]
    assert "name contains 'report'" in call_kwargs["params"]["q"]


@pytest.mark.asyncio
async def test_get_item():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    file_data = _make_drive_file(file_id="file-42", name="spec.docx")
    get_resp = _mock_response(file_data)
    _patch_session(adapter, get_resp)

    result = await adapter.get_item("file-42")

    assert isinstance(result, File)
    assert result.name == "spec.docx"
    assert result.source_id == "file-42"

    session = adapter._session
    call_args = session.request.call_args
    assert "/files/file-42" in call_args[0][1]


@pytest.mark.asyncio
async def test_create_item():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    created_resp = _mock_response({"id": "new-file-id"})
    _patch_session(adapter, created_resp)

    entity = File(
        id="local-1",
        name="notes.txt",
        path_or_url="",
        mime_type="text/plain",
        parent_folder="folder-1",
    )
    file_id = await adapter.create_item(entity)

    assert file_id == "new-file-id"
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "POST"
    body = call_args[1]["json"]
    assert body["name"] == "notes.txt"
    assert body["mimeType"] == "text/plain"
    assert body["parents"] == ["folder-1"]


@pytest.mark.asyncio
async def test_update_item():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    update_resp = _mock_response({"id": "file-1"})
    _patch_session(adapter, update_resp)

    result = await adapter.update_item("file-1", {"name": "renamed.pdf"})

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "PATCH"
    assert "/files/file-1" in call_args[0][1]
    assert call_args[1]["json"]["name"] == "renamed.pdf"


@pytest.mark.asyncio
async def test_update_item_empty_changes():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)

    result = await adapter.update_item("file-1", {})

    assert result is False


@pytest.mark.asyncio
async def test_delete_item():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    trash_resp = _mock_response({"id": "file-1", "trashed": True})
    _patch_session(adapter, trash_resp)

    result = await adapter.delete_item("file-1")

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "PATCH"
    assert "/files/file-1" in call_args[0][1]
    assert call_args[1]["json"]["trashed"] is True


@pytest.mark.asyncio
async def test_sync():
    oauth = _mock_oauth()
    adapter = GoogleDriveAdapter(oauth=oauth)
    files_resp = _mock_response({
        "files": [
            _make_drive_file(file_id="f-1"),
            _make_drive_file(file_id="f-2"),
        ]
    })
    _patch_session(adapter, files_resp)

    result = await adapter.sync()

    assert "f-1" in result.created
    assert "f-2" in result.created
    assert result.errors == []
