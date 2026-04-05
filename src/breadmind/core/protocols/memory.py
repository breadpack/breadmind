from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol
from breadmind.core.protocols.prompt import PromptBlock
from breadmind.core.protocols.provider import Message


@dataclass
class Episode:
    """에피소딕 메모리 항목."""
    id: str
    content: str
    keywords: list[str] = field(default_factory=list)
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KGTriple:
    """지식그래프 트리플."""
    subject: str
    predicate: str
    object: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryProtocol(Protocol):
    """메모리 읽기/쓰기/검색/압축 계약."""
    async def working_get(self, session_id: str) -> list[Message]: ...
    async def working_put(self, session_id: str, messages: list[Message]) -> None: ...
    async def working_compress(self, session_id: str, budget: int) -> None: ...
    async def episodic_search(self, query: str, limit: int = 5) -> list[Episode]: ...
    async def episodic_save(self, episode: Episode) -> None: ...
    async def semantic_query(self, entities: list[str]) -> list[KGTriple]: ...
    async def semantic_upsert(self, triples: list[KGTriple]) -> None: ...
    async def build_context_block(self, session_id: str, query: str, budget_tokens: int) -> PromptBlock: ...
    async def dream(self, session_id: str) -> None: ...
