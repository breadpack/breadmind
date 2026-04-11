"""Action handler that performs outbound HTTP requests."""

from __future__ import annotations

from typing import Any

import aiohttp

from breadmind.webhook.actions.base import ActionHandler, ActionResult, resolve_config
from breadmind.webhook.models import PipelineAction, PipelineContext


class HttpActionHandler(ActionHandler):
    """Make an HTTP request using aiohttp.

    Config keys:
        method (str): HTTP method (GET, POST, PUT, PATCH, DELETE, …).
        url (str): Request URL — supports Jinja2 template syntax.
        headers (dict[str, str]): Optional additional request headers.
        body (Any): Optional request body (JSON-serialised).

    If ``capture_response`` is True and ``response_variable`` is set,
    the response body text is stored in ``ctx.steps[response_variable]``.
    """

    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Resolve config templates and execute the HTTP request."""
        try:
            resolved = resolve_config(action.config, ctx)

            method: str = resolved.get("method", "GET").upper()
            url: str = resolved.get("url", "")
            extra_headers: dict[str, str] = resolved.get("headers", {})
            body: Any = resolved.get("body")

            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    headers=extra_headers if extra_headers else None,
                    json=body if body is not None else None,
                ) as response:
                    response_text = await response.text()
                    success = 200 <= response.status < 400

                    if action.capture_response and action.response_variable:
                        ctx.steps[action.response_variable] = response_text

                    if not success:
                        return ActionResult(
                            success=False,
                            output=response_text,
                            error=f"HTTP {response.status}",
                        )

                    return ActionResult(success=True, output=response_text)

        except Exception as exc:
            return ActionResult(success=False, error=str(exc))
