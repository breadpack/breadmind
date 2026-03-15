import asyncio
import logging
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WebhookEndpoint:
    id: str
    name: str
    path: str  # URL path suffix, e.g., "github-pr" -> /api/webhook/github-pr
    event_type: str  # "github", "gitlab", "generic", "ci"
    action: str  # message to send to agent (supports {payload} template)
    enabled: bool = True
    secret: str = ""  # optional webhook secret for verification
    received_count: int = 0
    last_received: datetime | None = None


class WebhookManager:
    """Manage incoming webhook endpoints."""

    def __init__(self):
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._message_handler = None
        self._event_log: list[dict] = []

    def set_message_handler(self, handler):
        self._message_handler = handler

    def add_endpoint(self, endpoint: WebhookEndpoint):
        self._endpoints[endpoint.id] = endpoint

    def remove_endpoint(self, endpoint_id: str) -> bool:
        return self._endpoints.pop(endpoint_id, None) is not None

    def get_endpoint_by_path(self, path: str) -> WebhookEndpoint | None:
        for ep in self._endpoints.values():
            if ep.path == path:
                return ep
        return None

    def get_endpoints(self) -> list[dict]:
        return [
            {"id": e.id, "name": e.name, "path": e.path, "event_type": e.event_type,
             "action": e.action, "enabled": e.enabled, "has_secret": bool(e.secret),
             "received_count": e.received_count,
             "last_received": e.last_received.isoformat() if e.last_received else None}
            for e in self._endpoints.values()
        ]

    async def handle_webhook(self, path: str, payload: dict, headers: dict = None) -> dict:
        """Process an incoming webhook."""
        endpoint = self.get_endpoint_by_path(path)
        if not endpoint:
            return {"status": "not_found", "error": f"No webhook endpoint for path: {path}"}
        if not endpoint.enabled:
            return {"status": "disabled", "error": "Webhook endpoint is disabled"}

        # TODO: verify secret if set (HMAC signature check)

        endpoint.received_count += 1
        endpoint.last_received = datetime.now(timezone.utc)

        # Build message from action template
        payload_str = json.dumps(payload, indent=2)[:2000]
        message = endpoint.action.replace("{payload}", payload_str)

        # Extract useful info from known event types
        summary = self._extract_summary(endpoint.event_type, payload)
        if summary:
            message = f"{message}\n\nSummary: {summary}"

        # Log event
        event = {
            "endpoint": endpoint.name, "path": path, "event_type": endpoint.event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary or "webhook received",
        }
        self._event_log.append(event)
        if len(self._event_log) > 100:
            self._event_log = self._event_log[-100:]

        # Send to agent
        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    result = await self._message_handler(message, user="webhook", channel=f"webhook:{path}")
                else:
                    result = self._message_handler(message, user="webhook", channel=f"webhook:{path}")
                return {"status": "ok", "response": str(result)[:500]}
            except Exception as e:
                return {"status": "error", "error": str(e)}

        return {"status": "ok", "message": "Webhook received (no handler)"}

    def _extract_summary(self, event_type: str, payload: dict) -> str:
        """Extract human-readable summary from known webhook payloads."""
        try:
            if event_type == "github":
                action = payload.get("action", "")
                if "pull_request" in payload:
                    pr = payload["pull_request"]
                    return f"PR #{pr.get('number')}: {pr.get('title')} ({action})"
                elif "issue" in payload:
                    issue = payload["issue"]
                    return f"Issue #{issue.get('number')}: {issue.get('title')} ({action})"
                elif "ref" in payload and "commits" in payload:
                    return f"Push to {payload.get('ref')}: {len(payload.get('commits', []))} commits"
            elif event_type == "gitlab":
                kind = payload.get("object_kind", "")
                if kind == "merge_request":
                    mr = payload.get("object_attributes", {})
                    return f"MR !{mr.get('iid')}: {mr.get('title')}"
                elif kind == "push":
                    return f"Push to {payload.get('ref')}: {payload.get('total_commits_count', 0)} commits"
            elif event_type == "ci":
                status = payload.get("status", payload.get("state", ""))
                name = payload.get("name", payload.get("pipeline", {}).get("id", ""))
                return f"CI: {name} — {status}"
        except Exception:
            pass
        return ""

    def get_event_log(self, limit: int = 50) -> list[dict]:
        return self._event_log[-limit:]
