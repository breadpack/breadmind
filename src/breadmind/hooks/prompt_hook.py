from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload, is_blockable
from breadmind.hooks.handler import _failure_decision

logger = logging.getLogger(__name__)


def _interpolate_env(value: str) -> str:
    """Expand $ENV_VAR or ${ENV_VAR} references in a string."""
    def _replace(m: re.Match) -> str:
        var = m.group(1) or m.group(2)
        return os.environ.get(var, m.group(0))

    return re.sub(r"\$\{(\w+)\}|\$(\w+)", _replace, value)


def _render_prompt(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with fallback to simple string replace."""
    try:
        from jinja2 import Environment, Undefined

        env = Environment(undefined=Undefined)
        return env.from_string(template).render(**context)
    except Exception:
        # Fallback: simple {{ key }} substitution
        result = template
        for key, val in context.items():
            result = result.replace("{{ " + key + " }}", str(val))
            result = result.replace("{{" + key + "}}", str(val))
        return result


@dataclass
class PromptHook:
    name: str
    event: HookEvent
    prompt: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 15.0
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    endpoint: str | None = None
    if_condition: str | list[str] | None = None

    async def _call_llm(self, rendered_prompt: str) -> str:
        """Call LLM and return raw text response."""
        # Resolution order:
        # 1. endpoint + api_key → direct HTTP (OpenAI-compatible)
        # 2. provider + model → create_provider(provider).chat(...)
        # 3. model only → system default provider with specified model
        # 4. nothing → system default provider

        api_key = _interpolate_env(self.api_key) if self.api_key else None
        endpoint = self.endpoint

        messages = [{"role": "user", "content": rendered_prompt}]

        if endpoint and api_key:
            return await self._call_direct_http(endpoint, api_key, messages)

        return await self._call_via_provider(messages)

    async def _call_direct_http(
        self,
        endpoint: str,
        api_key: str,
        messages: list[dict],
    ) -> str:
        """POST to an OpenAI-compatible endpoint directly."""
        import aiohttp

        model = self.model or "gpt-4o-mini"
        payload = {"model": model, "messages": messages}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    async def _call_via_provider(self, messages: list[dict]) -> str:
        """Call via the breadmind provider system."""
        from breadmind.llm.base import LLMMessage, LLMProvider
        from breadmind.llm.factory import _PROVIDER_REGISTRY

        llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages]

        provider: LLMProvider | None = None

        if self.provider:
            info = _PROVIDER_REGISTRY.get(self.provider)
            if info is not None:
                env_key = info.env_key
                raw_key = os.environ.get(env_key, "") if env_key else ""
                if raw_key:
                    provider = info.cls(api_key=raw_key, default_model=self.model)
                else:
                    provider = info.cls()

        if provider is None:
            # Use system default provider
            try:
                from breadmind.core.config import load_config
                config = load_config()
                from breadmind.llm.factory import create_provider
                provider = create_provider(config)
            except Exception:
                from breadmind.llm.ollama import OllamaProvider
                provider = OllamaProvider()

        response = await provider.chat(llm_messages, model=self.model)
        return response.content or ""

    def _parse_response(self, raw: str) -> tuple[bool, str]:
        """Parse LLM response. Returns (ok, reason). Lenient on parse failure."""
        text = raw.strip()
        # Try to extract JSON if wrapped in markdown
        if "```" in text:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                text = m.group(1)

        try:
            obj = json.loads(text)
            ok = bool(obj.get("ok", True))
            reason = str(obj.get("reason", ""))
            return ok, reason
        except (json.JSONDecodeError, AttributeError):
            # Non-JSON → PROCEED (lenient)
            logger.debug(
                "PromptHook '%s': non-JSON response, proceeding. raw=%r", self.name, raw
            )
            return True, raw

    async def run(self, payload: HookPayload) -> HookDecision:
        data = payload.data or {}
        context = {
            "event": payload.event.value,
            "data": data,
            "tool_name": data.get("tool_name", ""),
            "args": data.get("args", {}),
        }

        rendered = _render_prompt(self.prompt, context)

        try:
            raw = await asyncio.wait_for(
                self._call_llm(rendered),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError:
            d = _failure_decision(
                self.event,
                f"prompt hook '{self.name}' timeout after {self.timeout_sec}s",
            )
            d.hook_id = self.name
            return d
        except Exception as exc:
            d = _failure_decision(
                self.event,
                f"prompt hook '{self.name}' error: {exc}",
            )
            d.hook_id = self.name
            return d

        ok, reason = self._parse_response(raw)

        if ok:
            d = HookDecision.proceed(context=reason)
        else:
            if is_blockable(self.event):
                d = HookDecision.block(reason)
            else:
                # Observational event: log and proceed
                logger.info(
                    "PromptHook '%s': ok=false on observational event %s: %s",
                    self.name,
                    self.event.value,
                    reason,
                )
                d = HookDecision.proceed(context=reason)

        d.hook_id = self.name
        return d
