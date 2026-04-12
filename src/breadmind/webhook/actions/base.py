"""Base classes and utilities for webhook action handlers."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

import jinja2

from breadmind.webhook.models import PipelineAction, PipelineContext


@dataclass
class ActionResult:
    """Result of executing a pipeline action."""

    success: bool
    output: str = ""
    error: str = ""


def resolve_template(template_str: str, ctx: PipelineContext) -> str:
    """Render a Jinja2 template string using the pipeline context.

    Exposes ``payload``, ``headers``, ``endpoint``, ``steps``, and ``secrets``
    from *ctx* as template variables.

    Raises:
        jinja2.TemplateError: if the template is invalid or a variable is undefined.
    """
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    tpl = env.from_string(template_str)
    return tpl.render(
        payload=ctx.payload,
        headers=ctx.headers,
        endpoint=ctx.endpoint,
        steps=ctx.steps,
        secrets=ctx.secrets,
    )


def resolve_config(config: dict[str, Any], ctx: PipelineContext) -> dict[str, Any]:
    """Recursively resolve string values in *config* using :func:`resolve_template`.

    Non-string values are passed through unchanged.  Nested dicts are resolved
    recursively.
    """
    resolved: dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, str):
            resolved[key] = resolve_template(value, ctx)
        elif isinstance(value, dict):
            resolved[key] = resolve_config(value, ctx)
        else:
            resolved[key] = value
    return resolved


class ActionHandler(abc.ABC):
    """Abstract base class for all pipeline action handlers."""

    @abc.abstractmethod
    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Execute *action* within *ctx* and return an :class:`ActionResult`."""
