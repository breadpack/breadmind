"""Idempotency-Key handling for POST endpoints. Redis-backed, 24h TTL."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Final
from uuid import UUID


_TTL_SEC: Final[int] = 24 * 3600
_LOCK_TTL_SEC: Final[int] = 30  # In-progress lock TTL
_DEDUP_TTL_SEC: Final[int] = 24 * 3600


class IdempotencyConflict(Exception):
    """Same key reused with different request body hash."""


@dataclass(frozen=True, slots=True)
class CachedResponse:
    status: int
    body: bytes
    request_hash: str


class IdempotencyStore:
    IN_PROGRESS_SENTINEL = object()

    def __init__(self, redis):
        self._r = redis

    @staticmethod
    def _key(idem: str) -> str:
        return f"idem:{idem}"

    async def get_or_lock(self, key: str, *, request_hash: str):
        """Return CachedResponse if completed, IN_PROGRESS_SENTINEL if locked,
        None if newly acquired (caller proceeds and must call put())."""
        rkey = self._key(key)
        existing = await self._r.get(rkey)
        if existing is not None:
            obj = json.loads(existing)
            if obj.get("status") == "in_progress":
                if obj.get("request_hash") != request_hash:
                    raise IdempotencyConflict("hash mismatch on in-progress key")
                return self.IN_PROGRESS_SENTINEL
            if obj["request_hash"] != request_hash:
                raise IdempotencyConflict(
                    f"key {key} previously used with different request body"
                )
            return CachedResponse(
                status=obj["status_code"],
                body=obj["body"].encode("latin-1"),
                request_hash=obj["request_hash"],
            )
        # Acquire lock
        lock = json.dumps({"status": "in_progress", "request_hash": request_hash})
        ok = await self._r.set(rkey, lock, ex=_LOCK_TTL_SEC, nx=True)
        if not ok:
            return await self.get_or_lock(key, request_hash=request_hash)
        return None

    async def put(self, key: str, *, request_hash: str, status: int, body: bytes) -> None:
        obj = {
            "status_code": status,
            "body": body.decode("latin-1"),
            "request_hash": request_hash,
        }
        await self._r.set(self._key(key), json.dumps(obj), ex=_TTL_SEC)


def hash_request(method: str, path: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(method.encode())
    h.update(b"\0")
    h.update(path.encode())
    h.update(b"\0")
    h.update(body)
    return h.hexdigest()


class ClientMsgIdDedup:
    """Body-keyed message dedup: scope = (sender_id, channel_id, client_msg_id).

    Distinct from :class:`IdempotencyStore` (header-based, transport-layer
    protection): this guards against logical client retries / double-tap
    regardless of HTTP retry semantics. 24h TTL per spec D9.
    """

    def __init__(self, redis):
        self._r = redis

    @staticmethod
    def _key(sender_id: UUID, channel_id: UUID, client_msg_id: UUID) -> str:
        return f"msg:dedup:{sender_id}:{channel_id}:{client_msg_id}"

    async def lookup(
        self, *, sender_id: UUID, channel_id: UUID, client_msg_id: UUID,
    ) -> UUID | None:
        v = await self._r.get(self._key(sender_id, channel_id, client_msg_id))
        if v is None:
            return None
        s = v.decode() if isinstance(v, (bytes, bytearray)) else v
        return UUID(s)

    async def remember(
        self, *, sender_id: UUID, channel_id: UUID,
        client_msg_id: UUID, message_id: UUID,
    ) -> None:
        await self._r.set(
            self._key(sender_id, channel_id, client_msg_id),
            str(message_id),
            ex=_DEDUP_TTL_SEC,
        )
