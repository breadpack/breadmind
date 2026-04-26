"""Cursor-based pagination. Cursor encodes (created_at, id) HMAC-signed."""
from __future__ import annotations
import base64
import hmac
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


_CURSOR_KEY = os.environ.get("BREADMIND_MESSENGER_CURSOR_KEY", "dev-cursor-key").encode()


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CursorEnvelope:
    created_at: datetime
    id: UUID


def encode_cursor(env: CursorEnvelope) -> str:
    payload = json.dumps({
        "ts": env.created_at.isoformat(),
        "id": str(env.id),
    }, separators=(",", ":")).encode()
    sig = hmac.new(_CURSOR_KEY, payload, hashlib.sha256).digest()[:8]
    return base64.urlsafe_b64encode(payload + sig).decode().rstrip("=")


def decode_cursor(cursor: str) -> CursorEnvelope:
    try:
        padding = "=" * ((-len(cursor)) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
    except Exception as e:  # noqa: BLE001
        raise InvalidCursor(str(e)) from e
    if len(raw) < 9:
        raise InvalidCursor("cursor too short")
    payload, sig = raw[:-8], raw[-8:]
    expected = hmac.new(_CURSOR_KEY, payload, hashlib.sha256).digest()[:8]
    if not hmac.compare_digest(sig, expected):
        raise InvalidCursor("signature mismatch")
    try:
        obj = json.loads(payload.decode())
    except Exception as e:  # noqa: BLE001
        raise InvalidCursor("invalid json") from e
    return CursorEnvelope(
        created_at=datetime.fromisoformat(obj["ts"]),
        id=UUID(obj["id"]),
    )
