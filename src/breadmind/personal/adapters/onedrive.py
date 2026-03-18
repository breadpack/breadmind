"""Microsoft OneDrive adapter via Graph API."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import aiohttp

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import File
from breadmind.personal.oauth import OAuthManager

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _graph_item_to_file(item: dict[str, Any]) -> File:
    """Convert a OneDrive item resource to a BreadMind File."""
    parent_ref = item.get("parentReference")
    parent_folder = parent_ref.get("id") if parent_ref else None
    return File(
        id=str(uuid.uuid4()),
        name=item.get("name", ""),
        path_or_url=item.get("webUrl", ""),
        mime_type=item.get("file", {}).get("mimeType", "application/octet-stream"),
        size_bytes=int(item.get("size", 0)),
        source="onedrive",
        source_id=item.get("id", ""),
        parent_folder=parent_folder,
    )


class OneDriveAdapter(ServiceAdapter):
    """Adapter for Microsoft OneDrive via Graph API v1.0."""

    domain = "file"
    source = "onedrive"

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
        creds = await self._oauth.get_credentials("microsoft", self._user_id)
        if creds is None:
            raise RuntimeError("OneDriveAdapter is not authenticated")
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
        url = f"{GRAPH_BASE}{path}"
        headers = await self._headers()
        if json is not None:
            headers["Content-Type"] = "application/json"
        async with session.request(
            method, url, headers=headers, params=params, json=json
        ) as resp:
            if method == "DELETE" and resp.status == 204:
                return {}
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # ServiceAdapter interface
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: dict) -> bool:
        """Verify that valid Microsoft OAuth credentials exist."""
        try:
            creds = await self._oauth.get_credentials("microsoft", self._user_id)
            if creds is None:
                return False
            await self._request("GET", "/me/drive")
            return True
        except Exception:
            logger.exception("OneDrive authentication check failed")
            return False

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[File]:
        filters = filters or {}
        params: dict[str, str] = {"$top": str(min(limit, 1000))}

        if "name_contains" in filters and filters["name_contains"]:
            path = f"/me/drive/root/search(q='{filters['name_contains']}')"
        elif "parent" in filters:
            path = f"/me/drive/items/{filters['parent']}/children"
        else:
            path = "/me/drive/root/children"

        data = await self._request("GET", path, params=params)
        return [_graph_item_to_file(item) for item in data.get("value", [])]

    async def get_item(self, source_id: str) -> File | None:
        try:
            data = await self._request("GET", f"/me/drive/items/{source_id}")
            return _graph_item_to_file(data)
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            raise

    async def create_item(self, entity: File) -> str:
        """Create file metadata on OneDrive (no binary upload)."""
        parent = entity.parent_folder or "root"
        body: dict[str, Any] = {
            "name": entity.name,
            "file": {},
        }
        data = await self._request(
            "POST", f"/me/drive/items/{parent}/children", json=body
        )
        return data.get("id", "")

    async def update_item(self, source_id: str, changes: dict) -> bool:
        body: dict[str, Any] = {}
        if "name" in changes:
            body["name"] = changes["name"]
        if not body:
            return False
        await self._request("PATCH", f"/me/drive/items/{source_id}", json=body)
        return True

    async def delete_item(self, source_id: str) -> bool:
        """Delete an item from OneDrive."""
        await self._request("DELETE", f"/me/drive/items/{source_id}")
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Sync files from OneDrive."""
        files = await self.list_items(limit=100)
        return SyncResult(
            created=[f.source_id for f in files if f.source_id],
            updated=[],
            deleted=[],
            errors=[],
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
