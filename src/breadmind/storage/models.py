from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditEntry:
    action: str
    params: dict
    result: str  # ALLOWED / DENIED / APPROVED / REJECTED
    reason: str
    channel: str
    user: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    id: int | None = None


@dataclass
class EpisodicNote:
    content: str
    keywords: list[str]
    tags: list[str]
    context_description: str
    embedding: list[float] | None = None
    linked_note_ids: list[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    id: int | None = None
