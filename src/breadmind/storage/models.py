from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditEntry:
    action: str
    params: dict
    result: str  # ALLOWED / DENIED / APPROVED / REJECTED
    reason: str
    channel: str
    user: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None


@dataclass
class EpisodicNote:
    content: str
    keywords: list[str]
    tags: list[str]
    context_description: str
    embedding: list[float] | None = None
    linked_note_ids: list[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None
    decay_weight: float = 1.0


@dataclass
class KGEntity:
    id: str
    entity_type: str  # "user_preference" | "infra_component" | "pattern"
    name: str
    properties: dict = field(default_factory=dict)
    weight: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class KGRelation:
    source_id: str
    target_id: str
    relation_type: str  # "prefers" | "manages" | "depends_on" | "related_to"
    weight: float = 1.0
    properties: dict = field(default_factory=dict)
    id: int | None = None
