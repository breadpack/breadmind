import pytest

from breadmind.memory.episodic_recorder import RecorderConfig


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "BREADMIND_EPISODIC_NORMALIZE",
        "BREADMIND_EPISODIC_NORMALIZE_TIMEOUT_SEC",
        "BREADMIND_EPISODIC_QUEUE_MAX",
        "BREADMIND_EPISODIC_SEMAPHORE_SIZE",
    ):
        monkeypatch.delenv(k, raising=False)
    cfg = RecorderConfig.from_env()
    assert cfg.normalize is True
    assert cfg.timeout_sec == 8.0
    assert cfg.queue_max == 200
    assert cfg.semaphore_size == 8


def test_from_env_normalize_off_truthiness(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("off", "0", "false", "no", "OFF", "False"):
        monkeypatch.setenv("BREADMIND_EPISODIC_NORMALIZE", value)
        cfg = RecorderConfig.from_env()
        assert cfg.normalize is False, f"value={value!r} should disable normalize"


def test_from_env_normalize_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("on", "1", "true", "yes", "ON"):
        monkeypatch.setenv("BREADMIND_EPISODIC_NORMALIZE", value)
        cfg = RecorderConfig.from_env()
        assert cfg.normalize is True


def test_from_env_numeric_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREADMIND_EPISODIC_NORMALIZE_TIMEOUT_SEC", "12.5")
    monkeypatch.setenv("BREADMIND_EPISODIC_QUEUE_MAX", "50")
    monkeypatch.setenv("BREADMIND_EPISODIC_SEMAPHORE_SIZE", "4")
    cfg = RecorderConfig.from_env()
    assert cfg.timeout_sec == 12.5
    assert cfg.queue_max == 50
    assert cfg.semaphore_size == 4


def test_from_env_invalid_numeric_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREADMIND_EPISODIC_QUEUE_MAX", "not-a-number")
    monkeypatch.setenv("BREADMIND_EPISODIC_NORMALIZE_TIMEOUT_SEC", "huh")
    monkeypatch.setenv("BREADMIND_EPISODIC_SEMAPHORE_SIZE", "x")
    cfg = RecorderConfig.from_env()
    assert cfg.queue_max == 200  # default preserved
    assert cfg.timeout_sec == 8.0
    assert cfg.semaphore_size == 8
