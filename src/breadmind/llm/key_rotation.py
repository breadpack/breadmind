from __future__ import annotations

import asyncio


class KeyRotator:
    """동일 provider의 여러 API key를 round-robin으로 rotation한다.

    Rate limit에 걸린 key는 exhausted로 마킹되어 건너뛰며,
    모든 key가 exhausted이면 가장 먼저 마킹된 key를 재시도한다.
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("최소 1개 이상의 API key가 필요합니다")
        self._keys = list(keys)
        self._index = 0
        self._exhausted: set[int] = set()
        self._exhausted_order: list[int] = []  # 마킹 순서 추적
        self._lock = asyncio.Lock()

    @property
    def current_key(self) -> str:
        """현재 활성 key를 반환한다."""
        return self._keys[self._index]

    async def rotate(self) -> str:
        """다음 사용 가능한 key로 rotation한다.

        모든 key가 exhausted이면 가장 먼저 exhausted된 key를 복구하여 재시도한다.
        """
        async with self._lock:
            n = len(self._keys)

            # 사용 가능한 key 탐색 (현재 다음부터 한 바퀴)
            for offset in range(1, n + 1):
                candidate = (self._index + offset) % n
                if candidate not in self._exhausted:
                    self._index = candidate
                    return self._keys[self._index]

            # 모든 key가 exhausted — 가장 오래된 것을 복구
            oldest = self._exhausted_order[0]
            self._exhausted.discard(oldest)
            self._exhausted_order.remove(oldest)
            self._index = oldest
            return self._keys[self._index]

    async def mark_exhausted(self, key: str) -> None:
        """rate limit에 걸린 key를 exhausted로 마킹한다."""
        async with self._lock:
            try:
                idx = self._keys.index(key)
            except ValueError:
                return
            if idx not in self._exhausted:
                self._exhausted.add(idx)
                self._exhausted_order.append(idx)

    async def mark_recovered(self, key: str) -> None:
        """다시 사용 가능해진 key를 recovered로 마킹한다."""
        async with self._lock:
            try:
                idx = self._keys.index(key)
            except ValueError:
                return
            self._exhausted.discard(idx)
            if idx in self._exhausted_order:
                self._exhausted_order.remove(idx)

    @property
    def available_count(self) -> int:
        """현재 사용 가능한 key 수를 반환한다."""
        return len(self._keys) - len(self._exhausted)
