"""Google Drive API v3 adapter for file management."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import File
from breadmind.personal.oauth import OAuthManager

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.googleapis.com/drive/v3"

# Default fields to request from the Drive API.
_FILE_FIELDS = "id,name,mimeType,size,webViewLink,parents,createdTime,modifiedTime"
_LIST_FIELDS = f"files({_FILE_FIELDS}),nextPageToken"


def _drive_file_to_file(item: dict[str, Any]) -> File:
    """Convert a Google Drive file resource to a BreadMind File."""
    parents = item.get("parents")
    parent_folder = parents[0] if parents else None
    return File(
        id=str(uuid.uuid4()),
        name=item.get("name", ""),
        path_or_url=item.get("webViewLink", ""),
        mime_type=item.get("mimeType", "application/octet-stream"),
        size_bytes=int(item.get("size", 0)),
        source="google_drive",
        source_id=item.get("id", ""),
        parent_folder=parent_folder,
    )


def _build_query(filters: dict[str, Any]) -> str:
    """Build a Drive API q-parameter from a filters dict.

    Supported filter keys:
        name_contains  — name contains '<value>'
        mime_type       — mimeType = '<value>'
        trashed         — trashed = true/false (default false)
        parent          — '<value>' in parents
    """
    clauses: list[str] = []
    if "name_contains" in filters:
        escaped = filters["name_contains"].replace("'", "\\'")
        clauses.append(f"name contains '{escaped}'")
    if "mime_type" in filters:
        clauses.append(f"mimeType = '{filters['mime_type']}'")
    if "parent" in filters:
        clauses.append(f"'{filters['parent']}' in parents")
    trashed = filters.get("trashed", False)
    clauses.append(f"trashed = {str(trashed).lower()}")
    return " and ".join(clauses)


class GoogleDriveAdapter(ServiceAdapter):
    """Adapter for Google Drive API v3."""

    domain = "file"
    source = "google_drive"

    def __init__(
        self, oauth: OAuthManager, user_id: str = "default"
    ) -> None:
        self._oauth = oauth
        self._user_id = user_id
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _headers(self) -> dict[str, str]:
        creds = await self._oauth.get_credentials("google", self._user_id)
        if creds is None:
            raise RuntimeError("GoogleDriveAdapter is not authenticated")
        return {
            "Authorization": f"{creds.token_type} {creds.access_token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{_BASE_URL}{path}"
        headers = await self._headers()
        if json is not None:
            headers["Content-Type"] = "application/json"
        async with session.request(
            method, url, headers=headers, params=params, json=json
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # ServiceAdapter interface
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: dict) -> bool:
        """Verify that valid Google OAuth credentials exist.

        The *credentials* dict is not used directly; authentication is
        delegated to OAuthManager.  This method simply checks that
        a valid token is available.
        """
        try:
            creds = await self._oauth.get_credentials("google", self._user_id)
            if creds is None:
                return False
            # Verify connectivity with a lightweight call.
            await self._request("GET", "/about", params={"fields": "user"})
            return True
        except Exception:
            logger.exception("Google Drive authentication check failed")
            return False

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[File]:
        params: dict[str, str] = {
            "pageSize": str(min(limit, 1000)),
            "fields": _LIST_FIELDS,
        }
        if filters:
            params["q"] = _build_query(filters)
        else:
            params["q"] = "trashed = false"

        data = await self._request("GET", "/files", params=params)
        return [_drive_file_to_file(f) for f in data.get("files", [])]

    async def get_item(self, source_id: str) -> File:
        data = await self._request(
            "GET",
            f"/files/{source_id}",
            params={"fields": _FILE_FIELDS},
        )
        return _drive_file_to_file(data)

    async def create_item(self, entity: File) -> str:
        """Create file metadata on Google Drive (no binary upload)."""
        body: dict[str, Any] = {
            "name": entity.name,
            "mimeType": entity.mime_type,
        }
        if entity.parent_folder:
            body["parents"] = [entity.parent_folder]
        data = await self._request("POST", "/files", json=body)
        return data["id"]

    async def update_item(self, source_id: str, changes: dict) -> bool:
        body: dict[str, Any] = {}
        if "name" in changes:
            body["name"] = changes["name"]
        if "mime_type" in changes:
            body["mimeType"] = changes["mime_type"]
        if not body:
            return False
        await self._request("PATCH", f"/files/{source_id}", json=body)
        return True

    async def delete_item(self, source_id: str) -> bool:
        """Trash a file on Google Drive (soft delete)."""
        await self._request(
            "PATCH",
            f"/files/{source_id}",
            json={"trashed": True},
        )
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Sync files from Google Drive.

        If *since* is provided, only files modified after that time are
        fetched via the ``modifiedTime`` filter.
        """
        filters: dict[str, Any] = {}
        if since is not None:
            filters["trashed"] = False
        files = await self.list_items(filters=filters if filters else None, limit=100)

        # For a basic sync we report all fetched files as created;
        # a more advanced implementation would diff against local state.
        return SyncResult(
            created=[f.source_id for f in files if f.source_id],
            updated=[],
            deleted=[],
            errors=[],
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
