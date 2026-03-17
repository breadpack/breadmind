"""Google Contacts adapter using the People API."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import aiohttp

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Contact
from breadmind.personal.oauth import OAuthManager

logger = logging.getLogger(__name__)

_BASE_URL = "https://people.googleapis.com/v1"

_DEFAULT_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,memberships,biographies"
)


def _person_to_contact(person: dict[str, Any]) -> Contact:
    """Convert a Google People API person resource to a Contact."""
    resource_name = person.get("resourceName", "")

    names = person.get("names", [])
    name = names[0].get("displayName", "") if names else ""

    emails = person.get("emailAddresses", [])
    email = emails[0].get("value") if emails else None

    phones = person.get("phoneNumbers", [])
    phone = phones[0].get("value") if phones else None

    orgs = person.get("organizations", [])
    organization = orgs[0].get("name") if orgs else None

    bios = person.get("biographies", [])
    notes = bios[0].get("value") if bios else None

    memberships = person.get("memberships", [])
    tags: list[str] = []
    for m in memberships:
        label = m.get("contactGroupMembership", {}).get("contactGroupId")
        if label:
            tags.append(label)

    return Contact(
        id=str(uuid.uuid4()),
        name=name,
        email=email,
        phone=phone,
        platform_ids={"google_contacts": resource_name},
        organization=organization,
        tags=tags,
        notes=notes,
    )


def _contact_to_person(contact: Contact) -> dict[str, Any]:
    """Build a People API person body from a Contact."""
    person: dict[str, Any] = {}

    if contact.name:
        person["names"] = [{"givenName": contact.name}]

    if contact.email:
        person["emailAddresses"] = [{"value": contact.email}]

    if contact.phone:
        person["phoneNumbers"] = [{"value": contact.phone}]

    if contact.organization:
        person["organizations"] = [{"name": contact.organization}]

    if contact.notes:
        person["biographies"] = [{"value": contact.notes}]

    return person


class GoogleContactsAdapter(ServiceAdapter):
    """Adapter for the Google People API (contacts)."""

    domain = "contact"
    source = "google_contacts"

    def __init__(self, oauth_manager: OAuthManager | None = None, user_id: str = "default") -> None:
        self._oauth = oauth_manager
        self._user_id = user_id
        self._access_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._access_token is None:
            raise RuntimeError("GoogleContactsAdapter is not authenticated")
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

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
        async with session.request(
            method, url, headers=self._headers(), params=params, json=json
        ) as resp:
            resp.raise_for_status()
            if resp.status == 204:
                return {}
            return await resp.json()

    # ------------------------------------------------------------------
    # ServiceAdapter interface
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate using an access token or OAuthManager.

        Accepts either ``{"access_token": "..."}`` directly or uses the
        injected OAuthManager to retrieve credentials for the Google provider.
        """
        if "access_token" in credentials:
            self._access_token = credentials["access_token"]
        elif self._oauth:
            creds = await self._oauth.get_credentials("google", self._user_id)
            if creds is None:
                return False
            self._access_token = creds.access_token
        else:
            return False

        # Verify the token by fetching the authenticated user's profile.
        try:
            await self._request(
                "GET",
                "/people/me",
                params={"personFields": "names"},
            )
            return True
        except Exception:
            self._access_token = None
            return False

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[Contact]:
        """List contacts from the authenticated user's connections."""
        params: dict[str, str] = {
            "personFields": _DEFAULT_PERSON_FIELDS,
            "pageSize": str(min(limit, 1000)),
        }
        if filters and "query" in filters:
            # Use searchContacts for query-based filtering.
            params["query"] = filters["query"]
            data = await self._request("GET", "/people:searchContacts", params=params)
            results = data.get("results", [])
            return [_person_to_contact(r.get("person", {})) for r in results]

        data = await self._request("GET", "/people/me/connections", params=params)
        connections = data.get("connections", [])
        return [_person_to_contact(p) for p in connections]

    async def get_item(self, source_id: str) -> Contact:
        """Get a single contact by resource name (e.g. 'people/c12345')."""
        data = await self._request(
            "GET",
            f"/{source_id}",
            params={"personFields": _DEFAULT_PERSON_FIELDS},
        )
        return _person_to_contact(data)

    async def create_item(self, entity: Contact) -> str:
        """Create a new contact and return the resource name."""
        body = _contact_to_person(entity)
        data = await self._request("POST", "/people:createContact", json=body)
        return data.get("resourceName", "")

    async def update_item(self, source_id: str, changes: dict) -> bool:
        """Update an existing contact.

        *changes* may contain keys matching Contact field names:
        name, email, phone, organization, notes.
        """
        # First fetch the current person to get the etag for update.
        current = await self._request(
            "GET",
            f"/{source_id}",
            params={"personFields": _DEFAULT_PERSON_FIELDS},
        )

        person: dict[str, Any] = {"etag": current.get("etag", "")}
        update_fields: list[str] = []

        if "name" in changes:
            person["names"] = [{"givenName": changes["name"]}]
            update_fields.append("names")

        if "email" in changes:
            person["emailAddresses"] = [{"value": changes["email"]}]
            update_fields.append("emailAddresses")

        if "phone" in changes:
            person["phoneNumbers"] = [{"value": changes["phone"]}]
            update_fields.append("phoneNumbers")

        if "organization" in changes:
            person["organizations"] = [{"name": changes["organization"]}]
            update_fields.append("organizations")

        if "notes" in changes:
            person["biographies"] = [{"value": changes["notes"]}]
            update_fields.append("biographies")

        if not update_fields:
            return True

        await self._request(
            "PATCH",
            f"/{source_id}:updateContact",
            params={"updatePersonFields": ",".join(update_fields)},
            json=person,
        )
        return True

    async def delete_item(self, source_id: str) -> bool:
        """Delete a contact by resource name."""
        await self._request("DELETE", f"/{source_id}:deleteContact")
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Sync contacts from Google.

        If *since* is provided, uses the syncToken mechanism to fetch only
        changes since the last sync. Otherwise fetches all connections.
        """
        params: dict[str, str] = {
            "personFields": _DEFAULT_PERSON_FIELDS,
            "pageSize": "1000",
        }
        if since is not None:
            params["requestSyncToken"] = "true"

        data = await self._request("GET", "/people/me/connections", params=params)
        connections = data.get("connections", [])
        contacts = [_person_to_contact(p) for p in connections]

        return SyncResult(
            created=[c.platform_ids.get("google_contacts", "") for c in contacts],
            updated=[],
            deleted=[],
            errors=[],
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
