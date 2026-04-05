"""Microsoft Teams gateway using Bot Framework."""
from __future__ import annotations

import logging
from typing import Callable

from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


class TeamsGateway(MessengerGateway):
    """Microsoft Teams bot using Bot Framework REST API."""

    def __init__(self, app_id: str, app_password: str, on_message: Callable | None = None) -> None:
        super().__init__(platform="teams", on_message=on_message)
        self._app_id = app_id
        self._app_password = app_password
        self._access_token: str = ""
        self._service_url: str = ""

    async def start(self) -> None:
        """Authenticate with Bot Framework and mark as connected."""
        await self._authenticate()
        self._connected = True
        logger.info("Teams gateway started (app_id=%s)", self._app_id)

    async def stop(self) -> None:
        self._connected = False
        self._access_token = ""
        logger.info("Teams gateway stopped")

    async def send(self, channel_id: str, text: str) -> None:
        import aiohttp

        if not self._access_token:
            await self._authenticate()
        url = f"{self._service_url}/v3/conversations/{channel_id}/activities"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload = {"type": "message", "text": text}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 401:
                    await self._authenticate()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    async with session.post(url, headers=headers, json=payload) as retry:
                        if retry.status not in (200, 201):
                            logger.error("Teams send failed: %s", await retry.text())
                elif resp.status not in (200, 201):
                    logger.error("Teams send failed: %s", await resp.text())

    def _format_approval_message(self, action_name: str, params: dict, action_id: str) -> str:
        return f"Approval Required: {action_name}\nParams: {params}\nAction ID: {action_id}"

    async def handle_incoming(self, activity: dict) -> str | None:
        """Process incoming activity from Bot Framework webhook."""
        if activity.get("type") != "message":
            return None
        if not activity.get("text"):
            return None

        self._service_url = activity.get("serviceUrl", self._service_url)

        msg = self._create_incoming_message(
            text=activity["text"],
            user=activity.get("from", {}).get("id", ""),
            channel=activity.get("conversation", {}).get("id", ""),
        )

        if self._on_message:
            return await self._on_message(msg)
        return None

    async def _authenticate(self) -> None:
        """Get access token from Bot Framework OAuth endpoint."""
        import aiohttp

        url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._app_id,
            "client_secret": self._app_password,
            "scope": "https://api.botframework.com/.default",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                result = await resp.json()
                self._access_token = result.get("access_token", "")
