"""Webhook automation REST API routes: rules, pipelines, YAML import/export, dry-run."""
from __future__ import annotations

import logging

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from breadmind.web.dependencies import get_webhook_automation_store

logger = logging.getLogger(__name__)


def setup_webhook_automation_routes(app, app_state):
    """Register webhook automation routes on *app*."""

    # ── Rules ─────────────────────────────────────────────────────────────

    @app.get("/api/webhook/rules")
    async def list_rules(store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        return {"rules": [r.to_dict() for r in store.list_rules()]}

    @app.post("/api/webhook/rules")
    async def create_rule(request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        data = await request.json()
        from breadmind.webhook.models import WebhookRule
        rule = WebhookRule(
            name=data["name"],
            endpoint_id=data["endpoint_id"],
            condition=data["condition"],
            priority=data["priority"],
            pipeline_id=data["pipeline_id"],
            enabled=data.get("enabled", True),
        )
        store.add_rule(rule)
        return {"status": "ok", "rule": rule.to_dict()}

    @app.get("/api/webhook/rules/{rule_id}")
    async def get_rule(rule_id: str, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        rule = store.get_rule(rule_id)
        if rule is None:
            return JSONResponse(status_code=404, content={"error": f"Rule '{rule_id}' not found"})
        return {"rule": rule.to_dict()}

    @app.put("/api/webhook/rules/{rule_id}")
    async def update_rule(rule_id: str, request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        data = await request.json()
        updated = store.update_rule(rule_id, **data)
        if not updated:
            return JSONResponse(status_code=404, content={"error": f"Rule '{rule_id}' not found"})
        return {"status": "ok", "rule": store.get_rule(rule_id).to_dict()}

    @app.delete("/api/webhook/rules/{rule_id}")
    async def delete_rule(rule_id: str, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        removed = store.remove_rule(rule_id)
        if not removed:
            return JSONResponse(status_code=404, content={"error": f"Rule '{rule_id}' not found"})
        return {"status": "ok"}

    # ── Pipelines ─────────────────────────────────────────────────────────

    @app.get("/api/webhook/pipelines")
    async def list_pipelines(store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        return {"pipelines": [p.to_dict() for p in store.list_pipelines()]}

    @app.post("/api/webhook/pipelines")
    async def create_pipeline(request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        data = await request.json()
        from breadmind.webhook.models import Pipeline, PipelineAction
        actions = [PipelineAction.from_dict(a) for a in data.get("actions", [])]
        pipeline = Pipeline(
            name=data["name"],
            description=data.get("description", ""),
            actions=actions,
            enabled=data.get("enabled", True),
        )
        store.add_pipeline(pipeline)
        return {"status": "ok", "pipeline": pipeline.to_dict()}

    @app.get("/api/webhook/pipelines/{pipeline_id}")
    async def get_pipeline(pipeline_id: str, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        pipeline = store.get_pipeline(pipeline_id)
        if pipeline is None:
            return JSONResponse(status_code=404, content={"error": f"Pipeline '{pipeline_id}' not found"})
        return {"pipeline": pipeline.to_dict()}

    @app.put("/api/webhook/pipelines/{pipeline_id}")
    async def update_pipeline(pipeline_id: str, request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        data = await request.json()
        updated = store.update_pipeline(pipeline_id, **data)
        if not updated:
            return JSONResponse(status_code=404, content={"error": f"Pipeline '{pipeline_id}' not found"})
        return {"status": "ok", "pipeline": store.get_pipeline(pipeline_id).to_dict()}

    @app.delete("/api/webhook/pipelines/{pipeline_id}")
    async def delete_pipeline(pipeline_id: str, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        removed = store.remove_pipeline(pipeline_id)
        if not removed:
            return JSONResponse(status_code=404, content={"error": f"Pipeline '{pipeline_id}' not found"})
        return {"status": "ok"}

    # ── YAML export / import ──────────────────────────────────────────────

    @app.get("/api/webhook/export")
    async def export_yaml(store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        yaml_str = store.export_yaml()
        return PlainTextResponse(content=yaml_str, media_type="text/yaml")

    @app.post("/api/webhook/import")
    async def import_yaml(request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        yaml_str = (await request.body()).decode("utf-8")
        counts = store.import_yaml(yaml_str)
        return {"status": "ok", "imported": counts}

    # ── Dry-run rule test ─────────────────────────────────────────────────

    @app.post("/api/webhook/rules/{rule_id}/test")
    async def test_rule(rule_id: str, request: Request, store=Depends(get_webhook_automation_store)):
        if store is None:
            return JSONResponse(status_code=503, content={"error": "Webhook automation store not available"})
        rule = store.get_rule(rule_id)
        if rule is None:
            return JSONResponse(status_code=404, content={"error": f"Rule '{rule_id}' not found"})
        data = await request.json()
        payload = data.get("payload", {})
        headers = data.get("headers", {})
        from breadmind.webhook.rule_engine import ConditionError, RuleEngine
        try:
            matched = RuleEngine().evaluate_condition(rule.condition, payload=payload, headers=headers)
        except ConditionError as exc:
            return {"matched": False, "error": str(exc)}
        return {"matched": matched}
