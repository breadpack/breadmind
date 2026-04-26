from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from breadmind.core.otel import with_span
from breadmind.memory.episodic_store import EpisodicStore
from breadmind.memory.event_types import (
    SignalEvent, SignalKind, keyword_extract, stable_hash,
)
from breadmind.memory.metrics import (
    memory_normalize_latency_seconds,
    memory_normalize_total,
)
from breadmind.memory.redactor import redact as _redact
from breadmind.storage.models import EpisodicNote

logger = logging.getLogger(__name__)


@dataclass
class RecorderConfig:
    normalize: bool = True
    timeout_sec: float = 8.0
    semaphore_size: int = 8
    queue_max: int = 200

    @classmethod
    def from_env(cls) -> "RecorderConfig":
        import os

        def _bool(name: str, default: bool) -> bool:
            v = os.getenv(name)
            if v is None:
                return default
            return v.strip().lower() in {"1", "true", "yes", "on"}

        def _float(name: str, default: float) -> float:
            v = os.getenv(name)
            if v is None:
                return default
            try:
                return float(v)
            except ValueError:
                return default

        def _int(name: str, default: int) -> int:
            v = os.getenv(name)
            if v is None:
                return default
            try:
                return int(v)
            except ValueError:
                return default

        return cls(
            normalize=_bool("BREADMIND_EPISODIC_NORMALIZE", True),
            timeout_sec=_float("BREADMIND_EPISODIC_NORMALIZE_TIMEOUT_SEC", 8.0),
            semaphore_size=_int("BREADMIND_EPISODIC_SEMAPHORE_SIZE", 8),
            queue_max=_int("BREADMIND_EPISODIC_QUEUE_MAX", 200),
        )


_PROMPTS_ROOT = Path(__file__).parent.parent / "prompts" / "memory"
_jinja = Environment(
    loader=FileSystemLoader(str(_PROMPTS_ROOT)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    enable_async=False,
)


class _SkipRecording(Exception):
    pass


class _RedactedEventView:
    """Read-only view over a ``SignalEvent`` that masks PII / credentials
    on text-bearing fields before they're rendered into the LLM prompt.

    ``SignalEvent`` is a frozen dataclass, so we wrap it instead of mutating.
    Only the fields the Jinja template touches are redacted; deterministic
    fields (``kind``, ``tool_name``, ``tool_args``) pass through unchanged.
    """

    __slots__ = ("_evt",)

    def __init__(self, evt: SignalEvent):
        self._evt = evt

    @property
    def kind(self) -> SignalKind:
        return self._evt.kind

    @property
    def tool_name(self) -> str | None:
        return self._evt.tool_name

    @property
    def tool_args(self) -> dict | None:
        return self._evt.tool_args

    @property
    def user_message(self) -> str | None:
        return _redact(self._evt.user_message) if self._evt.user_message else self._evt.user_message

    @property
    def tool_result_text(self) -> str | None:
        return _redact(self._evt.tool_result_text) if self._evt.tool_result_text else self._evt.tool_result_text

    @property
    def prior_turn_summary(self) -> str | None:
        return _redact(self._evt.prior_turn_summary) if self._evt.prior_turn_summary else self._evt.prior_turn_summary


class EpisodicRecorder:
    def __init__(self, *, store: EpisodicStore, llm, config: RecorderConfig | None = None):
        self.store = store
        self.llm = llm
        self.config = config or RecorderConfig()
        self._sem = asyncio.Semaphore(self.config.semaphore_size)
        self._inflight = 0

    async def record(self, event: SignalEvent) -> None:
        try:
            note = await self._build_note(event)
        except _SkipRecording:
            self._bump_outcome("skipped_by_llm")
            return
        except Exception:
            logger.exception("EpisodicRecorder.record build failed")
            return
        try:
            await self.store.write(note)
        except Exception:
            logger.exception("EpisodicRecorder.record store.write failed")

    @staticmethod
    def _bump_outcome(outcome: str) -> None:
        """Best-effort metric increment — never raises."""
        try:
            memory_normalize_total.labels(outcome=outcome).inc()
        except Exception:  # pragma: no cover - defensive
            logger.debug("memory_normalize_total inc failed", exc_info=True)

    async def _build_note(self, event: SignalEvent) -> EpisodicNote:
        if not self.config.normalize:
            self._bump_outcome("raw_fallback")
            return self._raw_note(event)
        # Backpressure: if too many normalizations are already in flight,
        # skip the LLM and emit a raw note. The check runs synchronously
        # before any await, so it is race-free under asyncio.
        if self._inflight >= self.config.queue_max:
            self._bump_outcome("raw_fallback")
            return self._raw_note(event)
        self._inflight += 1
        try:
            async with self._sem:
                try:
                    with memory_normalize_latency_seconds.time():
                        payload = await asyncio.wait_for(
                            self._normalize_with_llm(event),
                            timeout=self.config.timeout_sec,
                        )
                except Exception:
                    logger.warning("episodic normalize failed; falling back to raw", exc_info=True)
                    self._bump_outcome("llm_failed")
                    self._bump_outcome("raw_fallback")
                    return self._raw_note(event)
        finally:
            self._inflight -= 1
        if not payload.get("should_record", True):
            raise _SkipRecording()
        self._bump_outcome("recorded")
        return EpisodicNote(
            content=self._raw_content(event),
            keywords=list(payload.get("keywords") or []) or keyword_extract(self._raw_content(event)),
            tags=[],
            context_description=event.kind.value,
            kind=event.kind.value,
            tool_name=event.tool_name,
            tool_args_digest=stable_hash(event.tool_args),
            outcome=payload.get("outcome") or self._default_outcome(event.kind),
            session_id=event.session_id,
            user_id=event.user_id,
            summary=payload.get("summary") or self._raw_summary(event),
            pinned=event.kind is SignalKind.EXPLICIT_PIN,
        )

    async def _normalize_with_llm(self, event: SignalEvent) -> dict:
        tmpl = _jinja.get_template("episodic_normalize.j2")
        # Defensive PII / credential redaction (Section 13). The Jinja
        # template renders with autoescape OFF for LLM consumption, so we
        # mask sensitive shapes on the text-bearing fields BEFORE render.
        # Deterministic fields (kind, tool_name, tool_args, outcome) pass
        # through unchanged.
        redacted = _RedactedEventView(event)
        prompt = tmpl.render(event=redacted)
        with with_span(
            "memory.recorder.normalize",
            attributes={"signal.kind": event.kind.value},
        ):
            return await self.llm.complete_json(prompt)

    def _raw_note(self, event: SignalEvent) -> EpisodicNote:
        return EpisodicNote(
            content=self._raw_content(event),
            keywords=keyword_extract(self._raw_content(event)),
            tags=[],
            context_description=event.kind.value,
            kind=event.kind.value,
            tool_name=event.tool_name,
            tool_args_digest=stable_hash(event.tool_args),
            outcome=self._default_outcome(event.kind),
            session_id=event.session_id,
            user_id=event.user_id,
            summary=self._raw_summary(event),
            pinned=event.kind is SignalKind.EXPLICIT_PIN,
        )

    def _raw_content(self, event: SignalEvent) -> str:
        bits: list[str] = []
        if event.tool_name:
            bits.append(f"tool={event.tool_name} args={event.tool_args}")
        if event.tool_result_text:
            bits.append(f"result={event.tool_result_text}")
        if event.user_message:
            bits.append(f"user={event.user_message}")
        return "\n".join(bits) or event.kind.value

    def _raw_summary(self, event: SignalEvent) -> str:
        return f"{event.kind.value}: {event.tool_name or 'turn'} {self._default_outcome(event.kind)}"

    @staticmethod
    def _default_outcome(kind: SignalKind) -> str:
        if kind is SignalKind.TOOL_FAILED:
            return "failure"
        if kind is SignalKind.TOOL_EXECUTED:
            return "success"
        return "neutral"


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


class LLMJsonAdapter:
    """Wraps any provider that exposes `await complete(prompt) -> str` and
    parses a JSON object out of the response."""

    def __init__(self, base):
        self.base = base

    async def complete_json(self, prompt: str) -> dict:
        text = await self.base.complete(prompt)
        # Try strict first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = _JSON_BLOCK.search(text or "")
        if not m:
            raise ValueError("LLM response contained no JSON object")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM JSON parse failed: {e}") from e
