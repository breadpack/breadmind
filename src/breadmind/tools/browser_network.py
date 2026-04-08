"""CDP-based network monitoring with traffic capture, URL blocking, and HAR export."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestEntry:
    """Represents a captured network request/response pair."""

    url: str
    method: str
    status: int
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    body_size: int
    duration_ms: float
    resource_type: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this entry."""
        return {
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "request_headers": self.request_headers,
            "response_headers": self.response_headers,
            "body_size": self.body_size,
            "duration_ms": self.duration_ms,
            "resource_type": self.resource_type,
            "timestamp": self.timestamp,
        }


class NetworkMonitor:
    """Monitor network traffic via the Chrome DevTools Protocol (CDP)."""

    def __init__(self, cdp_session: Any, max_entries: int = 1000) -> None:
        self._cdp = cdp_session
        self._max_entries = max_entries
        self._entries: list[RequestEntry] = []
        self._pending: dict[str, dict[str, Any]] = {}
        self._url_filters: list[str] | None = None
        self._capturing: bool = False

    async def start_capture(self, url_filters: list[str] | None = None) -> None:
        """Enable network capture and register CDP event handlers."""
        self._entries = []
        self._pending = {}
        self._url_filters = url_filters
        self._capturing = True

        await self._cdp.send("Network.enable", {})
        self._cdp.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._cdp.on("Network.responseReceived", self._on_response_received)

    async def stop_capture(self) -> list[RequestEntry]:
        """Disable network capture and return all collected entries."""
        self._capturing = False
        await self._cdp.send("Network.disable", {})
        return list(self._entries)

    def _matches_filters(self, url: str) -> bool:
        """Return True if url passes the active url_filters (substring match)."""
        if not self._url_filters:
            return True
        return any(f in url for f in self._url_filters)

    def _on_request_will_be_sent(self, params: dict[str, Any]) -> None:
        """Handle CDP Network.requestWillBeSent event."""
        if not self._capturing:
            return

        request_id: str = params["requestId"]
        request = params["request"]
        url: str = request["url"]

        if not self._matches_filters(url):
            return

        self._pending[request_id] = {
            "url": url,
            "method": request["method"],
            "request_headers": request.get("headers", {}),
            "resource_type": params.get("type", "other").lower(),
            "timestamp": params["timestamp"],
        }

    def _on_response_received(self, params: dict[str, Any]) -> None:
        """Handle CDP Network.responseReceived event."""
        if not self._capturing:
            return

        request_id: str = params["requestId"]
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return

        response = params["response"]
        response_timestamp: float = params["timestamp"]
        duration_ms: float = (response_timestamp - pending["timestamp"]) * 1000.0

        entry = RequestEntry(
            url=pending["url"],
            method=pending["method"],
            status=response["status"],
            request_headers=pending["request_headers"],
            response_headers=response.get("headers", {}),
            body_size=response.get("encodedDataLength", 0),
            duration_ms=duration_ms,
            resource_type=pending["resource_type"],
            timestamp=pending["timestamp"],
        )

        self._entries.append(entry)

        # Evict oldest entries when over the cap
        if len(self._entries) > self._max_entries:
            excess = len(self._entries) - self._max_entries
            self._entries = self._entries[excess:]

    async def block_urls(self, patterns: list[str]) -> None:
        """Block network requests matching the given URL patterns."""
        await self._cdp.send("Network.setBlockedURLs", {"urls": patterns})

    async def unblock_urls(self) -> None:
        """Remove all URL blocking rules."""
        await self._cdp.send("Network.setBlockedURLs", {"urls": []})

    def export_har(self) -> dict[str, Any]:
        """Export captured traffic as a HAR-like dict (HTTP Archive format)."""
        har_entries = []
        for entry in self._entries:
            har_entries.append({
                "startedDateTime": entry.timestamp,
                "time": entry.duration_ms,
                "request": {
                    "method": entry.method,
                    "url": entry.url,
                    "headers": [{"name": k, "value": v} for k, v in entry.request_headers.items()],
                    "bodySize": -1,
                    "headersSize": -1,
                },
                "response": {
                    "status": entry.status,
                    "headers": [{"name": k, "value": v} for k, v in entry.response_headers.items()],
                    "bodySize": entry.body_size,
                    "headersSize": -1,
                },
                "resourceType": entry.resource_type,
            })

        return {
            "log": {
                "version": "1.2",
                "creator": {"name": "BreadMind NetworkMonitor", "version": "1.0"},
                "entries": har_entries,
            }
        }

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of captured traffic."""
        by_type: dict[str, int] = {}
        total_size = 0
        total_duration = 0.0

        for entry in self._entries:
            by_type[entry.resource_type] = by_type.get(entry.resource_type, 0) + 1
            total_size += entry.body_size
            total_duration += entry.duration_ms

        count = len(self._entries)
        avg_duration = total_duration / count if count > 0 else 0.0

        return {
            "total_count": count,
            "by_type": by_type,
            "total_size_bytes": total_size,
            "avg_duration_ms": avg_duration,
        }
