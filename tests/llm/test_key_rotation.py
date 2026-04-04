from __future__ import annotations

import pytest

from breadmind.llm.key_rotation import KeyRotator


class TestKeyRotatorInit:
    def test_empty_keys_raises_value_error(self):
        with pytest.raises(ValueError, match="최소 1개 이상"):
            KeyRotator([])

    def test_single_key(self):
        rotator = KeyRotator(["key1"])
        assert rotator.current_key == "key1"
        assert rotator.available_count == 1


class TestRoundRobinRotation:
    async def test_rotates_through_keys_in_order(self):
        rotator = KeyRotator(["k1", "k2", "k3"])
        assert rotator.current_key == "k1"

        key = await rotator.rotate()
        assert key == "k2"
        assert rotator.current_key == "k2"

        key = await rotator.rotate()
        assert key == "k3"
        assert rotator.current_key == "k3"

        # wraps around
        key = await rotator.rotate()
        assert key == "k1"
        assert rotator.current_key == "k1"

    async def test_single_key_rotation_returns_same_key(self):
        rotator = KeyRotator(["only"])
        key = await rotator.rotate()
        assert key == "only"
        assert rotator.current_key == "only"


class TestExhaustedKeys:
    async def test_skips_exhausted_key(self):
        rotator = KeyRotator(["k1", "k2", "k3"])

        await rotator.mark_exhausted("k2")
        assert rotator.available_count == 2

        key = await rotator.rotate()
        assert key == "k3"  # k2 skipped

    async def test_skips_multiple_exhausted_keys(self):
        rotator = KeyRotator(["k1", "k2", "k3", "k4"])

        await rotator.mark_exhausted("k2")
        await rotator.mark_exhausted("k3")
        assert rotator.available_count == 2

        key = await rotator.rotate()
        assert key == "k4"  # k2, k3 skipped

    async def test_all_exhausted_recovers_oldest(self):
        rotator = KeyRotator(["k1", "k2", "k3"])

        await rotator.mark_exhausted("k1")
        await rotator.mark_exhausted("k2")
        await rotator.mark_exhausted("k3")
        assert rotator.available_count == 0

        # rotate should recover k1 (oldest exhausted)
        key = await rotator.rotate()
        assert key == "k1"
        assert rotator.available_count == 1

    async def test_mark_recovered_restores_key(self):
        rotator = KeyRotator(["k1", "k2", "k3"])

        await rotator.mark_exhausted("k2")
        assert rotator.available_count == 2

        await rotator.mark_recovered("k2")
        assert rotator.available_count == 3

    async def test_mark_exhausted_unknown_key_is_noop(self):
        rotator = KeyRotator(["k1"])
        await rotator.mark_exhausted("unknown")
        assert rotator.available_count == 1

    async def test_mark_recovered_unknown_key_is_noop(self):
        rotator = KeyRotator(["k1"])
        await rotator.mark_recovered("unknown")
        assert rotator.available_count == 1

    async def test_double_exhaust_same_key(self):
        rotator = KeyRotator(["k1", "k2"])
        await rotator.mark_exhausted("k1")
        await rotator.mark_exhausted("k1")  # idempotent
        assert rotator.available_count == 1


class TestExhaustedRecoveryOrder:
    async def test_oldest_exhausted_recovered_first(self):
        rotator = KeyRotator(["k1", "k2", "k3"])

        # exhaust in order: k1 -> k2 -> k3
        await rotator.mark_exhausted("k1")
        await rotator.mark_exhausted("k2")
        await rotator.mark_exhausted("k3")

        # first recovery should be k1 (oldest)
        key = await rotator.rotate()
        assert key == "k1"

        # exhaust k1 again, now k2 is oldest
        await rotator.mark_exhausted("k1")
        key = await rotator.rotate()
        assert key == "k2"
