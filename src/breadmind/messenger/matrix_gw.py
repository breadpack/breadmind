"""Matrix protocol gateway."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable

from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


class MatrixGateway(MessengerGateway):
    def __init__(
        self,
        homeserver: str,
        access_token: str,
        user_id: str = "",
        on_message: Callable | None = None,
    ) -> None:
        super().__init__(platform="matrix", on_message=on_message)
        self._homeserver = homeserver.rstrip("/")
        self._access_token = access_token
        self._user_id = user_id
        self._sync_task: asyncio.Task | None = None
        self._since: str = ""

    async def start(self) -> None:
        self._connected = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Matrix gateway started (homeserver=%s)", self._homeserver)

    async def stop(self) -> None:
        self._connected = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("Matrix gateway stopped")

    async def send(self, channel_id: str, text: str) -> None:
        import aiohttp

        txn_id = str(uuid.uuid4())
        url = (
            f"{self._homeserver}/_matrix/client/v3/rooms/"
            f"{channel_id}/send/m.room.message/{txn_id}"
        )
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload = {"msgtype": "m.text", "body": text}
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status not in (200, 201):
                    logger.error("Matrix send failed: %s", await resp.text())

    def _format_approval_message(self, action_name: str, params: dict, action_id: str) -> str:
        return (
            f"\U0001f510 승인 요청: {action_name}\n"
            f"파라미터: {params}\n"
            f"Action ID: {action_id}"
        )

    async def _sync_loop(self) -> None:
        """Long-poll sync loop to receive messages."""
        import aiohttp

        while self._connected:
            try:
                params = {"timeout": "30000"}
                if self._since:
                    params["since"] = self._since
                url = f"{self._homeserver}/_matrix/client/v3/sync"
                headers = {"Authorization": f"Bearer {self._access_token}"}

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=headers, params=params
                    ) as resp:
                        if resp.status != 200:
                            await asyncio.sleep(5)
                            continue
                        data = await resp.json()

                self._since = data.get("next_batch", self._since)

                # Process room events
                for room_id, room_data in (
                    data.get("rooms", {}).get("join", {}).items()
                ):
                    for event in room_data.get("timeline", {}).get(
                        "events", []
                    ):
                        if (
                            event.get("type") == "m.room.message"
                            and event.get("content", {}).get("msgtype")
                            == "m.text"
                            and event.get("sender") != self._user_id
                        ):
                            msg = self._create_incoming_message(
                                text=event["content"]["body"],
                                user=event["sender"],
                                channel=room_id,
                            )
                            if self._on_message:
                                response = await self._on_message(msg)
                                if response:
                                    await self.send(room_id, response)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Matrix sync error")
                await asyncio.sleep(5)
