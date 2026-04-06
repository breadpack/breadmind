"""In-memory storage for webhook rules and pipelines with DB persistence and YAML import/export."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml

from breadmind.webhook.models import Pipeline, WebhookRule

DB_KEY_RULES = "webhook_automation_rules"
DB_KEY_PIPELINES = "webhook_automation_pipelines"


class WebhookAutomationStore:
    """In-memory store for webhook rules and pipelines with optional DB persistence."""

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._rules: dict[str, WebhookRule] = {}
        self._pipelines: dict[str, Pipeline] = {}

    # ------------------------------------------------------------------
    # Rules CRUD
    # ------------------------------------------------------------------

    def add_rule(self, rule: WebhookRule) -> None:
        """Add a rule to the store."""
        self._rules[rule.id] = rule

    def get_rule(self, rule_id: str) -> WebhookRule | None:
        """Return the rule with the given ID, or None if not found."""
        return self._rules.get(rule_id)

    def list_rules(self) -> list[WebhookRule]:
        """Return all rules."""
        return list(self._rules.values())

    def get_rules_for_endpoint(self, endpoint_id: str) -> list[WebhookRule]:
        """Return all rules associated with the given endpoint."""
        return [r for r in self._rules.values() if r.endpoint_id == endpoint_id]

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if it existed, False otherwise."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def update_rule(self, rule_id: str, **kwargs: Any) -> bool:
        """Update attributes on a rule and refresh updated_at. Returns True if found."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        for key, value in kwargs.items():
            setattr(rule, key, value)
        rule.updated_at = datetime.now(timezone.utc)
        return True

    # ------------------------------------------------------------------
    # Pipelines CRUD
    # ------------------------------------------------------------------

    def add_pipeline(self, pipeline: Pipeline) -> None:
        """Add a pipeline to the store."""
        self._pipelines[pipeline.id] = pipeline

    def get_pipeline(self, pipeline_id: str) -> Pipeline | None:
        """Return the pipeline with the given ID, or None if not found."""
        return self._pipelines.get(pipeline_id)

    def list_pipelines(self) -> list[Pipeline]:
        """Return all pipelines."""
        return list(self._pipelines.values())

    def remove_pipeline(self, pipeline_id: str) -> bool:
        """Remove a pipeline by ID. Returns True if it existed, False otherwise."""
        if pipeline_id in self._pipelines:
            del self._pipelines[pipeline_id]
            return True
        return False

    def update_pipeline(self, pipeline_id: str, **kwargs: Any) -> bool:
        """Update attributes on a pipeline and refresh updated_at. Returns True if found."""
        pipeline = self._pipelines.get(pipeline_id)
        if pipeline is None:
            return False
        for key, value in kwargs.items():
            setattr(pipeline, key, value)
        pipeline.updated_at = datetime.now(timezone.utc)
        return True

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    async def save(self) -> None:
        """Persist rules and pipelines to the database."""
        if self._db is None:
            return
        rules_data = [r.to_dict() for r in self._rules.values()]
        pipelines_data = [p.to_dict() for p in self._pipelines.values()]
        await self._db.set_setting(DB_KEY_RULES, rules_data)
        await self._db.set_setting(DB_KEY_PIPELINES, pipelines_data)

    async def load(self) -> None:
        """Load rules and pipelines from the database, replacing current in-memory state."""
        if self._db is None:
            return
        rules_data = await self._db.get_setting(DB_KEY_RULES)
        pipelines_data = await self._db.get_setting(DB_KEY_PIPELINES)

        if rules_data:
            self._rules = {r["id"]: WebhookRule.from_dict(r) for r in rules_data}
        if pipelines_data:
            self._pipelines = {p["id"]: Pipeline.from_dict(p) for p in pipelines_data}

    # ------------------------------------------------------------------
    # YAML import / export
    # ------------------------------------------------------------------

    def export_yaml(self) -> str:
        """Export all rules and pipelines as a YAML string."""
        data = {
            "rules": [r.to_dict() for r in self._rules.values()],
            "pipelines": [p.to_dict() for p in self._pipelines.values()],
        }
        return yaml.dump(data, allow_unicode=True, sort_keys=False)

    def import_yaml(self, yaml_str: str) -> dict[str, int]:
        """Import rules and pipelines from a YAML string.

        Returns a dict with counts of imported items: {"rules": N, "pipelines": N}.
        """
        data = yaml.safe_load(yaml_str) or {}
        rules_imported = 0
        pipelines_imported = 0

        for rule_data in data.get("rules", []):
            rule = WebhookRule.from_dict(rule_data)
            self.add_rule(rule)
            rules_imported += 1

        for pipeline_data in data.get("pipelines", []):
            pipeline = Pipeline.from_dict(pipeline_data)
            self.add_pipeline(pipeline)
            pipelines_imported += 1

        return {"rules": rules_imported, "pipelines": pipelines_imported}
