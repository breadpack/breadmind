"""LLM-based auto safety classifier for tool calls.

When autonomy is set to ``auto-llm``, the classifier asks an LLM provider
to evaluate whether a tool invocation is safe, destructive, or ambiguous.
Results are cached with a configurable TTL to avoid redundant LLM calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from breadmind.core.protocols import Message, ProviderProtocol

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a security classifier for an AI agent's tool execution system.
Evaluate the following tool call and return a JSON object with these fields:
- "safe": boolean — true if the action is safe to execute autonomously
- "confidence": float 0-1 — how confident you are in the assessment
- "reason": string — brief explanation
- "suggested_action": "allow" | "deny" | "ask_user"

Evaluate based on:
1. Data loss risk — could this destroy or corrupt data?
2. Irreversibility — can the action be undone?
3. Scope of impact — does it affect one resource or many?
4. User intent alignment — does it match what a typical user would expect?

Respond ONLY with the JSON object, no markdown fences or extra text.\
"""


@dataclass
class SafetyClassification:
    """Result of an LLM-based safety evaluation."""

    safe: bool
    confidence: float
    reason: str
    suggested_action: str  # "allow" | "deny" | "ask_user"


class AutoSafetyClassifier:
    """Classify tool calls via an LLM provider with result caching."""

    def __init__(
        self,
        provider: ProviderProtocol,
        cache_ttl: int = 300,
    ) -> None:
        self._provider = provider
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[SafetyClassification, float]] = {}

    # ── Public API ────────────────────────────────────────────────────

    async def classify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: str = "",
    ) -> SafetyClassification:
        """Ask the LLM to evaluate a tool call's safety.

        If a cached result exists and has not expired, it is returned
        directly without calling the provider.
        """
        cache_key = self._cache_key(tool_name, arguments)

        cached = self._cache.get(cache_key)
        if cached is not None:
            classification, ts = cached
            if time.monotonic() - ts < self._cache_ttl:
                return classification
            # Expired — remove stale entry
            del self._cache[cache_key]

        messages = self._build_classification_prompt(tool_name, arguments, context)

        try:
            response = await self._provider.chat(messages)
            classification = self._parse_response(response.content or "")
        except Exception:
            logger.exception("LLM classification failed; falling back to ask_user")
            classification = SafetyClassification(
                safe=False,
                confidence=0.0,
                reason="Classification failed — LLM error",
                suggested_action="ask_user",
            )

        # Apply confidence threshold: low confidence always defers to user
        if classification.confidence < 0.8 and classification.suggested_action != "deny":
            classification.suggested_action = "ask_user"

        self._cache[cache_key] = (classification, time.monotonic())
        return classification

    # ── Prompt construction ───────────────────────────────────────────

    def _build_classification_prompt(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: str,
    ) -> list[Message]:
        """Build the message list sent to the LLM for classification."""
        user_content = (
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(arguments, default=str)}\n"
        )
        if context:
            user_content += f"Context: {context}\n"

        return [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_content),
        ]

    # ── Response parsing ──────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> SafetyClassification:
        """Parse the LLM's JSON response into a ``SafetyClassification``."""
        try:
            data = json.loads(text)
            return SafetyClassification(
                safe=bool(data.get("safe", False)),
                confidence=float(data.get("confidence", 0.0)),
                reason=str(data.get("reason", "")),
                suggested_action=str(data.get("suggested_action", "ask_user")),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Failed to parse LLM classification response: %s", text[:200])
            return SafetyClassification(
                safe=False,
                confidence=0.0,
                reason="Failed to parse LLM response",
                suggested_action="ask_user",
            )

    # ── Cache helpers ─────────────────────────────────────────────────

    @staticmethod
    def _cache_key(tool_name: str, arguments: dict[str, Any]) -> str:
        """Deterministic cache key from tool name + arguments."""
        args_json = json.dumps(arguments, sort_keys=True, default=str)
        args_hash = hashlib.sha256(args_json.encode()).hexdigest()[:16]
        return f"{tool_name}:{args_hash}"
