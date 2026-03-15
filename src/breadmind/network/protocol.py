"""Message envelope, serialization, HMAC integrity, sequence validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(Enum):
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    HEARTBEAT = "heartbeat"
    SYNC = "sync"
    ROLE_UPDATE = "role_update"
    COMMAND = "command"


class MessageIntegrityError(Exception):
    """HMAC verification failed."""


class MessageSequenceError(Exception):
    """Sequence number validation failed."""


@dataclass
class MessageEnvelope:
    protocol_version: int
    id: str
    seq: int
    type: MessageType
    source: str
    target: str
    timestamp: str
    payload: dict[str, Any]
    trace_id: str | None = None
    reply_to: str | None = None
    hmac: str | None = None


def create_message(
    type: MessageType,
    source: str,
    target: str,
    payload: dict[str, Any],
    seq: int = 0,
    trace_id: str | None = None,
    reply_to: str | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=1,
        id=str(uuid.uuid4()),
        seq=seq,
        type=type,
        source=source,
        target=target,
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        trace_id=trace_id,
        reply_to=reply_to,
    )


def _compute_hmac(data: dict, session_key: bytes) -> str:
    """Compute HMAC-SHA256 over message body (excluding hmac field)."""
    body = {k: v for k, v in data.items() if k != "hmac"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(session_key, canonical.encode(), hashlib.sha256).hexdigest()


def serialize_message(msg: MessageEnvelope, session_key: bytes) -> str:
    data = asdict(msg)
    data["type"] = msg.type.value
    data["hmac"] = _compute_hmac(data, session_key)
    return json.dumps(data)


def deserialize_message(raw: str, session_key: bytes) -> MessageEnvelope:
    data = json.loads(raw)
    received_hmac = data.get("hmac")
    expected_hmac = _compute_hmac(data, session_key)
    if not hmac.compare_digest(received_hmac or "", expected_hmac):
        raise MessageIntegrityError("HMAC verification failed")
    return MessageEnvelope(
        protocol_version=data["protocol_version"],
        id=data["id"],
        seq=data["seq"],
        type=MessageType(data["type"]),
        source=data["source"],
        target=data["target"],
        timestamp=data["timestamp"],
        payload=data["payload"],
        trace_id=data.get("trace_id"),
        reply_to=data.get("reply_to"),
        hmac=received_hmac,
    )


class SequenceTracker:
    """Monotonic sequence number tracker for replay protection."""

    def __init__(self) -> None:
        self._outgoing: int = 0
        self._incoming: int = 0

    def next_seq(self) -> int:
        self._outgoing += 1
        return self._outgoing

    def validate_incoming(self, seq: int) -> None:
        expected = self._incoming + 1
        if seq != expected:
            raise MessageSequenceError(
                f"Expected seq {expected}, got {seq}"
            )
        self._incoming = seq
