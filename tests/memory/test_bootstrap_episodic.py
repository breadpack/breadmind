"""Smoke tests verifying the episodic recorder circuit wiring.

We test the helper extracted from init_core_services rather than the full
bootstrap path, because init_core_services drags in role registry,
plugin loading, embeddings, and skill discovery — far beyond the wiring
under test. The helper covers the entire wiring contract: db gating,
RecorderConfig env propagation, and graceful degradation on errors.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class _PostgresLikeDb:
    """Minimal duck-type matching PostgresEpisodicStore expectations."""

    def __init__(self) -> None:
        self.fetch = AsyncMock(return_value=[])
        self.execute = AsyncMock(return_value=None)
        self.fetchrow = AsyncMock(return_value=None)
        self.fetchval = AsyncMock(return_value=None)


@pytest.fixture
def pg_db() -> _PostgresLikeDb:
    return _PostgresLikeDb()


@pytest.fixture
def fake_provider() -> MagicMock:
    p = MagicMock()
    p.generate = AsyncMock(return_value=SimpleNamespace(content="{}"))
    return p


def test_build_episodic_circuit_wires_with_postgres_db(
    monkeypatch: pytest.MonkeyPatch,
    pg_db: _PostgresLikeDb,
    fake_provider: MagicMock,
) -> None:
    from breadmind.core.bootstrap import build_episodic_circuit

    monkeypatch.delenv("BREADMIND_EPISODIC_NORMALIZE", raising=False)
    store, recorder, detector = build_episodic_circuit(pg_db, fake_provider)

    assert store is not None, "episodic_store must be wired"
    assert recorder is not None, "episodic_recorder must be wired"
    assert detector is not None, "signal_detector must be wired"
    assert recorder.store is store
    assert recorder.config.normalize is True
    assert recorder.config.queue_max == 200


def test_build_episodic_circuit_normalize_off_via_env(
    monkeypatch: pytest.MonkeyPatch,
    pg_db: _PostgresLikeDb,
    fake_provider: MagicMock,
) -> None:
    from breadmind.core.bootstrap import build_episodic_circuit

    monkeypatch.setenv("BREADMIND_EPISODIC_NORMALIZE", "off")
    _, recorder, _ = build_episodic_circuit(pg_db, fake_provider)
    assert recorder is not None
    assert recorder.config.normalize is False


def test_build_episodic_circuit_dormant_when_db_lacks_fetch_execute(
    fake_provider: MagicMock,
) -> None:
    from breadmind.core.bootstrap import build_episodic_circuit

    file_db = SimpleNamespace()  # no .fetch / .execute
    store, recorder, detector = build_episodic_circuit(file_db, fake_provider)
    assert store is None
    assert recorder is None
    assert detector is None


def test_build_episodic_circuit_dormant_when_db_is_none(
    fake_provider: MagicMock,
) -> None:
    from breadmind.core.bootstrap import build_episodic_circuit

    store, recorder, detector = build_episodic_circuit(None, fake_provider)
    assert (store, recorder, detector) == (None, None, None)


def test_build_episodic_circuit_swallows_construction_errors(
    monkeypatch: pytest.MonkeyPatch,
    pg_db: _PostgresLikeDb,
    fake_provider: MagicMock,
) -> None:
    """If PostgresEpisodicStore raises, the helper must return all None."""
    from breadmind.core.bootstrap import build_episodic_circuit
    from breadmind.memory import episodic_store as store_mod

    class _BoomStore:
        def __init__(self, db):
            raise RuntimeError("boom")

    monkeypatch.setattr(store_mod, "PostgresEpisodicStore", _BoomStore)
    store, recorder, detector = build_episodic_circuit(pg_db, fake_provider)
    assert (store, recorder, detector) == (None, None, None)
