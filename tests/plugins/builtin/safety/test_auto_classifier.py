"""Tests for AutoSafetyClassifier and guard.py auto-llm integration."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.core.protocols import LLMResponse, Message, TokenUsage
from breadmind.plugins.builtin.safety.auto_classifier import (
    AutoSafetyClassifier,
    SafetyClassification,
)
from breadmind.plugins.builtin.safety.guard import SafetyGuard, SafetyVerdict


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_provider(response_json: dict) -> MagicMock:
    """Create a mock ProviderProtocol that returns *response_json* as text."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content=json.dumps(response_json),
        tool_calls=[],
        usage=TokenUsage(),
        stop_reason="end_turn",
    ))
    return provider


# ── AutoSafetyClassifier tests ───────────────────────────────────────


async def test_classify_safe_tool_returns_allow():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.95,
        "reason": "Read-only operation",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider)

    result = await classifier.classify("file_read", {"path": "/tmp/data.txt"})

    assert result.safe is True
    assert result.confidence == 0.95
    assert result.suggested_action == "allow"
    provider.chat.assert_awaited_once()


async def test_classify_destructive_tool_returns_deny():
    provider = _mock_provider({
        "safe": False,
        "confidence": 0.92,
        "reason": "Deletes all pods in the cluster",
        "suggested_action": "deny",
    })
    classifier = AutoSafetyClassifier(provider=provider)

    result = await classifier.classify(
        "k8s_pods_delete",
        {"namespace": "default", "all": True},
    )

    assert result.safe is False
    assert result.suggested_action == "deny"


async def test_classification_caching():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.9,
        "reason": "Safe",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider, cache_ttl=300)

    args = {"cmd": "ls"}
    r1 = await classifier.classify("shell_exec", args)
    r2 = await classifier.classify("shell_exec", args)

    # Provider should only be called once — second call hits cache
    assert provider.chat.await_count == 1
    assert r1.suggested_action == r2.suggested_action


async def test_low_confidence_falls_back_to_ask_user():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.5,
        "reason": "Uncertain about scope",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider)

    result = await classifier.classify("shell_exec", {"cmd": "something ambiguous"})

    # Low confidence should override to ask_user
    assert result.suggested_action == "ask_user"


async def test_cache_ttl_expiry():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.95,
        "reason": "Safe",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider, cache_ttl=1)

    args = {"cmd": "ls"}
    await classifier.classify("shell_exec", args)

    # Manually expire the cache entry
    for key in classifier._cache:
        classification, _ = classifier._cache[key]
        classifier._cache[key] = (classification, time.monotonic() - 10)

    await classifier.classify("shell_exec", args)

    # Provider called twice — first call + expired-cache call
    assert provider.chat.await_count == 2


# ── Guard integration tests ──────────────────────────────────────────


async def test_guard_auto_llm_mode_uses_classifier():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.95,
        "reason": "Read-only",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider)
    guard = SafetyGuard(autonomy="auto-llm", auto_classifier=classifier)

    verdict = await guard.check_async("file_read", {"path": "/tmp/x"})

    assert verdict.allowed is True
    assert not verdict.needs_approval
    provider.chat.assert_awaited_once()


async def test_guard_auto_llm_deny():
    provider = _mock_provider({
        "safe": False,
        "confidence": 0.9,
        "reason": "Destructive operation",
        "suggested_action": "deny",
    })
    classifier = AutoSafetyClassifier(provider=provider)
    guard = SafetyGuard(autonomy="auto-llm", auto_classifier=classifier)

    verdict = await guard.check_async("rm_all", {"path": "/"})

    assert not verdict.allowed
    assert "Destructive" in verdict.reason


async def test_guard_auto_llm_ask_user():
    provider = _mock_provider({
        "safe": True,
        "confidence": 0.5,
        "reason": "Ambiguous",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider)
    guard = SafetyGuard(autonomy="auto-llm", auto_classifier=classifier)

    verdict = await guard.check_async("shell_exec", {"cmd": "curl something"})

    assert verdict.allowed is True
    assert verdict.needs_approval is True


async def test_guard_check_async_backward_compatible():
    """check_async with non-auto-llm modes should behave like sync check."""
    guard = SafetyGuard(autonomy="confirm-destructive")

    verdict_async = await guard.check_async("safe_tool", {"arg": "val"})
    verdict_sync = guard.check("safe_tool", {"arg": "val"})

    assert verdict_async.allowed == verdict_sync.allowed
    assert verdict_async.needs_approval == verdict_sync.needs_approval


async def test_guard_check_async_blocked_pattern():
    """Blocked patterns should be enforced even in auto-llm mode."""
    provider = _mock_provider({
        "safe": True,
        "confidence": 1.0,
        "reason": "Safe",
        "suggested_action": "allow",
    })
    classifier = AutoSafetyClassifier(provider=provider)
    guard = SafetyGuard(
        autonomy="auto-llm",
        blocked_patterns=["evil_cmd"],
        auto_classifier=classifier,
    )

    verdict = await guard.check_async("shell_exec", {"cmd": "evil_cmd"})

    assert not verdict.allowed
    # LLM should NOT have been called — blocked-pattern short-circuits
    provider.chat.assert_not_awaited()
