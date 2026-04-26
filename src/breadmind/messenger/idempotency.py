"""Idempotency-Key handling for POST endpoints. Redis-backed, 24h TTL."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Final


_TTL_SEC: Final[int] = 24 * 3600
_LOCK_TTL_SEC: Final[int] = 30  # In-progress lock TTL


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
