"""Outgoing webhook dispatcher — POST events to external URLs."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from breadmind.core.events import EventBus

logger = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────


@dataclass
class WebhookTarget:
    """A destination that receives outgoing webhook events."""

    url: str
    events: list[str] = field(default_factory=list)
    secret: str | None = None
    enabled: bool = True
    retry_count: int = 3


@dataclass
class WebhookPayload:
    """Wire format for an outgoing webhook delivery."""

    event_type: str
    timestamp: str
    data: dict[str, Any]
    delivery_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Signing ───────────────────────────────────────────────────────────


def sign_payload(payload: str, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest of *payload* using *secret*."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


# ── Dispatcher ────────────────────────────────────────────────────────


class OutgoingWebhookDispatcher:
    """Dispatch events as HTTP POST requests to registered webhook targets."""

    def __init__(self, targets: list[WebhookTarget] | None = None) -> None:
        self._targets: list[WebhookTarget] = list(targets) if targets else []
        self._delivery_log: deque[dict[str, Any]] = deque(maxlen=200)

    # -- Target management -------------------------------------------------

    def add_target(self, target: WebhookTarget) -> None:
        self._targets.append(target)

    def remove_target(self, url: str) -> None:
        self._targets = [t for t in self._targets if t.url != url]

    # -- Delivery log ------------------------------------------------------

    def get_delivery_log(self, limit: int = 50) -> list[dict[str, Any]]:
        items = list(self._delivery_log)
        return items[-limit:]

    # -- Dispatch ----------------------------------------------------------

    async def dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        """Send *event_type* to every matching & enabled target."""
        payload_obj = WebhookPayload(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
        )
        payload_json = json.dumps(
            {
                "event_type": payload_obj.event_type,
                "timestamp": payload_obj.timestamp,
                "data": payload_obj.data,
                "delivery_id": payload_obj.delivery_id,
            }
        )

        tasks = []
        for target in self._targets:
            if not target.enabled:
                continue
            if target.events and event_type not in target.events:
                continue
            tasks.append(
                self._deliver(target, payload_obj, payload_json)
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def dispatch_async(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire-and-forget variant of :meth:`dispatch`."""
        asyncio.create_task(self.dispatch(event_type, data))

    # -- Internal delivery -------------------------------------------------

    async def _deliver(
        self,
        target: WebhookTarget,
        payload_obj: WebhookPayload,
        payload_json: str,
    ) -> None:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Webhook-Event": payload_obj.event_type,
            "X-Delivery-Id": payload_obj.delivery_id,
        }
        if target.secret:
            headers["X-Webhook-Signature"] = sign_payload(payload_json, target.secret)

        last_exc: Exception | None = None
        attempts = max(target.retry_count, 1)

        for attempt in range(attempts):
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        target.url, data=payload_json, headers=headers
                    ) as resp:
                        if resp.status < 400:
                            self._record_log(
                                target, payload_obj, status=resp.status, success=True
                            )
                            return
                        last_exc = Exception(
                            f"HTTP {resp.status}: {await resp.text()}"
                        )
            except Exception as exc:
                last_exc = exc

            # Exponential back-off before next retry
            if attempt < attempts - 1:
                await asyncio.sleep(2 ** attempt)

        # All retries exhausted
        self._record_log(
            target,
            payload_obj,
            status=None,
            success=False,
            error=str(last_exc),
        )
        logger.warning(
            "Webhook delivery failed for %s after %d attempts: %s",
            target.url,
            attempts,
            last_exc,
        )

    def _record_log(
        self,
        target: WebhookTarget,
        payload_obj: WebhookPayload,
        *,
        status: int | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "delivery_id": payload_obj.delivery_id,
            "url": target.url,
            "event_type": payload_obj.event_type,
            "timestamp": payload_obj.timestamp,
            "status": status,
            "success": success,
        }
        if error:
            entry["error"] = error
        self._delivery_log.append(entry)

    # -- EventBus integration ----------------------------------------------

    def connect_to_eventbus(
        self, eventbus: EventBus, event_types: list[str]
    ) -> None:
        """Register as a listener on *eventbus* for the given event types."""
        for event_type in event_types:
            async def _handler(data: Any, _et: str = event_type) -> None:
                await self.dispatch(_et, data if isinstance(data, dict) else {"data": data})

            eventbus.on(event_type, _handler)
