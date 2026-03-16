"""Monitoring, usage, audit, and metrics routes."""
from __future__ import annotations

import logging
from dataclasses import asdict
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


def setup_monitoring_routes(r: APIRouter, app_state):
    """Register /api/monitoring/*, /api/usage, /api/audit, /api/metrics routes."""

    @r.get("/api/monitoring/events")
    async def get_monitoring_events():
        return {"events": app_state._events[-50:]}

    @r.get("/api/monitoring/status")
    async def get_monitoring_status():
        if app_state._monitoring_engine:
            status = app_state._monitoring_engine.get_status()
            return {
                "running": status["running"],
                "rules": status["rules_count"],
                "events_total": len(app_state._events),
            }
        return {"running": False, "rules": 0, "events_total": 0}

    @r.get("/api/usage")
    async def get_usage():
        """Return token usage and cost stats from agent."""
        if app_state._agent and hasattr(app_state._agent, 'get_usage'):
            usage = app_state._agent.get_usage()
            return {"usage": usage}
        return {"usage": {}}

    @r.get("/api/audit")
    async def get_audit():
        """Return recent audit log entries."""
        if app_state._audit_logger and hasattr(app_state._audit_logger, 'get_recent'):
            entries = app_state._audit_logger.get_recent(50)
            serialized = []
            for e in entries:
                if hasattr(e, '__dataclass_fields__'):
                    serialized.append(asdict(e))
                elif isinstance(e, dict):
                    serialized.append(e)
                else:
                    serialized.append(str(e))
            return {"entries": serialized}
        return {"entries": []}

    @r.get("/api/metrics")
    async def get_metrics():
        """Return tool execution metrics."""
        if app_state._metrics_collector and hasattr(app_state._metrics_collector, 'get_summary'):
            return {"metrics": app_state._metrics_collector.get_summary()}
        return {"metrics": {}}
