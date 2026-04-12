import asyncio
import hashlib
import hmac
import logging
import json
from datetime import datetime, timezone
from dataclasses import dataclass

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
    fallback_strategy: str = "forward_to_agent"  # "drop" | "forward_to_agent" | "default_pipeline"
    fallback_pipeline_id: str = ""
    permission_level: str = "standard"  # matches PermissionLevel enum values


class WebhookManager:
    """Manage incoming webhook endpoints."""

    def __init__(self):
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._message_handler = None
        self._event_log: list[dict] = []
        self._store = None
        self._rule_engine = None
        self._pipeline_executor = None

    def set_message_handler(self, handler):
        self._message_handler = handler

    def set_automation(self, store=None, rule_engine=None, pipeline_executor=None):
        self._store = store
        self._rule_engine = rule_engine
        self._pipeline_executor = pipeline_executor

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

    def _verify_secret(self, endpoint: WebhookEndpoint, payload_bytes: bytes, headers: dict) -> bool:
        """Verify webhook signature using HMAC-SHA256."""
        if not endpoint.secret:
            return True  # No secret configured — allow without verification

        # GitHub: X-Hub-Signature-256
        github_sig = headers.get("x-hub-signature-256", "")
        if github_sig:
            expected = "sha256=" + hmac.new(
                endpoint.secret.encode(), payload_bytes, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(github_sig, expected)

        # GitLab: X-Gitlab-Token
        gitlab_token = headers.get("x-gitlab-token", "")
        if gitlab_token:
            return hmac.compare_digest(gitlab_token, endpoint.secret)

        # Generic: X-Webhook-Secret
        generic_secret = headers.get("x-webhook-secret", "")
        if generic_secret:
            return hmac.compare_digest(generic_secret, endpoint.secret)

        # If secret is set but no signature provided, reject
        return False

    async def handle_webhook(self, path: str, payload: dict, headers: dict = None, payload_bytes: bytes = b"") -> dict:
        """Process an incoming webhook."""
        endpoint = self.get_endpoint_by_path(path)
        if not endpoint:
            return {"status": "not_found", "error": f"No webhook endpoint for path: {path}"}
        if not endpoint.enabled:
            return {"status": "disabled", "error": "Webhook endpoint is disabled"}

        # Verify secret
        if not self._verify_secret(endpoint, payload_bytes, headers or {}):
            return {"status": "unauthorized", "error": "Invalid webhook signature"}

        endpoint.received_count += 1
        endpoint.last_received = datetime.now(timezone.utc)

        # Extract useful info from known event types
        summary = self._extract_summary(endpoint.event_type, payload)

        # Log event
        self._log_event(endpoint, path, summary)

        # Try automation rules
        if self._store and self._rule_engine and self._pipeline_executor:
            rules = self._store.get_rules_for_endpoint(endpoint.id)
            matched_rule = self._rule_engine.match_rules(rules, payload, headers or {})
            if matched_rule:
                pipeline = self._store.get_pipeline(matched_rule.pipeline_id)
                if pipeline:
                    from breadmind.webhook.models import PipelineContext, PermissionLevel
                    ctx = PipelineContext(payload=payload, headers=headers or {}, endpoint=path)
                    perm = PermissionLevel(endpoint.permission_level)
                    log = await self._pipeline_executor.execute(pipeline, ctx, perm)
                    return {"status": "ok", "pipeline": pipeline.name, "success": log.success, "actions_executed": len(log.action_results)}

        # No rule matched — apply fallback strategy
        return await self._apply_fallback(endpoint, path, payload, summary)

    def _log_event(self, endpoint: WebhookEndpoint, path: str, summary: str | None) -> None:
        """Append a webhook event to the in-memory event log (capped at 100 entries)."""
        event = {
            "endpoint": endpoint.name, "path": path, "event_type": endpoint.event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary or "webhook received",
        }
        self._event_log.append(event)
        if len(self._event_log) > 100:
            self._event_log = self._event_log[-100:]

    async def _apply_fallback(self, endpoint: WebhookEndpoint, path: str, payload: dict, summary: str | None) -> dict:
        """Apply the endpoint's fallback strategy when no rule matched."""
        strategy = endpoint.fallback_strategy

        if strategy == "drop":
            return {"status": "ok", "message": "Webhook dropped (no matching rules)"}

        if strategy == "default_pipeline" and endpoint.fallback_pipeline_id:
            if self._store and self._pipeline_executor:
                pipeline = self._store.get_pipeline(endpoint.fallback_pipeline_id)
                if pipeline:
                    from breadmind.webhook.models import PipelineContext, PermissionLevel
                    ctx = PipelineContext(payload=payload, headers={}, endpoint=path)
                    perm = PermissionLevel(endpoint.permission_level)
                    log = await self._pipeline_executor.execute(pipeline, ctx, perm)
                    return {"status": "ok", "pipeline": pipeline.name, "success": log.success}

        # Default: forward_to_agent (existing behavior)
        payload_str = json.dumps(payload, indent=2)[:2000]
        message = endpoint.action.replace("{payload}", payload_str)
        if summary:
            message = f"{message}\n\nSummary: {summary}"

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
