from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

import aiohttp

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import _failure_decision, _parse_shell_decision
from breadmind.hooks.http_guard import SSRFError, validate_url

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{?(\w+)\}?")


@dataclass
class HttpHook:
    name: str
    event: HookEvent
    url: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "POST"
    allow_http: bool = False
    allowed_hosts: list[str] | None = None
    if_condition: str | list[str] | None = None

    def _interpolate_env(self) -> tuple[str, dict[str, str]]:
        """Interpolate $VAR and ${VAR} patterns from environment variables."""
        def _replace(text: str) -> str:
            return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), text)

        url = _replace(self.url)
        headers = {k: _replace(v) for k, v in self.headers.items()}
        return url, headers

    async def run(self, payload: HookPayload) -> HookDecision:
        url, headers = self._interpolate_env()

        # SSRF validation before making any network call
        try:
            validate_url(url, allow_http=self.allow_http, allowed_hosts=self.allowed_hosts)
        except SSRFError as exc:
            d = _failure_decision(self.event, f"SSRF blocked: {exc}")
            d.hook_id = self.name
            return d

        body = json.dumps(
            {"event": payload.event.value, "data": payload.data, "hook_name": self.name},
            default=str,
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    self.method,
                    url,
                    data=body,
                    headers={"Content-Type": "application/json", **headers},
                    timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                ) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        d = _failure_decision(
                            self.event,
                            f"HTTP {resp.status} from {url}",
                        )
                        d.hook_id = self.name
                        return d

                    try:
                        resp_json = await resp.json()
                        stdout = json.dumps(resp_json)
                    except Exception:
                        stdout = ""

                    decision = _parse_shell_decision(stdout, self.event)
                    decision.hook_id = self.name
                    return decision

        except asyncio.TimeoutError:
            d = _failure_decision(
                self.event,
                f"http hook '{self.name}' timeout after {self.timeout_sec}s",
            )
            d.hook_id = self.name
            return d
        except Exception as exc:
            d = _failure_decision(self.event, f"http hook '{self.name}' error: {exc}")
            d.hook_id = self.name
            return d
