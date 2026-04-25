from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from breadmind.memory.episodic_store import EpisodicStore
from breadmind.memory.event_types import (
    SignalEvent, SignalKind, keyword_extract, stable_hash,
)
from breadmind.storage.models import EpisodicNote

logger = logging.getLogger(__name__)


@dataclass
class RecorderConfig:
    normalize: bool = True
    timeout_sec: float = 8.0
    semaphore_size: int = 8
    queue_max: int = 200


_PROMPTS_ROOT = Path(__file__).parent.parent / "prompts" / "memory"
_jinja = Environment(
    loader=FileSystemLoader(str(_PROMPTS_ROOT)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    enable_async=False,
)


class _SkipRecording(Exception):
    pass


class EpisodicRecorder:
    def __init__(self, *, store: EpisodicStore, llm, config: RecorderConfig | None = None):
        self.store = store
        self.llm = llm
        self.config = config or RecorderConfig()
        self._sem = asyncio.Semaphore(self.config.semaphore_size)

    async def record(self, event: SignalEvent) -> None:
        try:
            note = await self._build_note(event)
        except _SkipRecording:
            return
        except Exception:
            logger.exception("EpisodicRecorder.record build failed")
            return
        try:
            await self.store.write(note)
        except Exception:
            logger.exception("EpisodicRecorder.record store.write failed")

    async def _build_note(self, event: SignalEvent) -> EpisodicNote:
        if not self.config.normalize:
            return self._raw_note(event)
        async with self._sem:
            try:
                payload = await asyncio.wait_for(
                    self._normalize_with_llm(event),
                    timeout=self.config.timeout_sec,
                )
            except Exception:
                logger.warning("episodic normalize failed; falling back to raw", exc_info=True)
                return self._raw_note(event)
        if not payload.get("should_record", True):
            raise _SkipRecording()
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
        prompt = tmpl.render(event=event)
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
