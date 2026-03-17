"""Monitoring, usage, audit, and metrics routes."""
from __future__ import annotations

import logging
from dataclasses import asdict
from fastapi import APIRouter, Depends

from breadmind.web.dependencies import (
    get_agent, get_audit_logger, get_events,
    get_metrics_collector, get_monitoring_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


def setup_monitoring_routes(r: APIRouter, app_state):
    """Register /api/monitoring/*, /api/usage, /api/audit, /api/metrics routes."""

    @r.get("/api/monitoring/events")
    async def get_monitoring_events(events=Depends(get_events)):
        return {"events": events[-50:]}

    @r.get("/api/monitoring/status")
    async def get_monitoring_status(
        monitoring_engine=Depends(get_monitoring_engine),
        events=Depends(get_events),
    ):
        if monitoring_engine:
            status = monitoring_engine.get_status()
            return {
                "running": status["running"],
                "rules": status["rules_count"],
                "events_total": len(events),
            }
        return {"running": False, "rules": 0, "events_total": 0}

    @r.get("/api/usage")
    async def get_usage(agent=Depends(get_agent)):
        """Return token usage and cost stats from agent."""
        if agent and hasattr(agent, 'get_usage'):
            usage = agent.get_usage()
            return {"usage": usage}
        return {"usage": {}}

    @r.get("/api/audit")
    async def get_audit(audit_logger=Depends(get_audit_logger)):
        """Return recent audit log entries."""
        if audit_logger and hasattr(audit_logger, 'get_recent'):
            entries = audit_logger.get_recent(50)
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
    async def get_metrics(metrics_collector=Depends(get_metrics_collector)):
        """Return tool execution metrics."""
        if metrics_collector and hasattr(metrics_collector, 'get_summary'):
            return {"metrics": metrics_collector.get_summary()}
        return {"metrics": {}}
