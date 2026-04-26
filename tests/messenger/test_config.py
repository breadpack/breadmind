import os
from breadmind.messenger.config import MessengerConfig


def test_defaults_when_env_missing(monkeypatch):
    for k in list(os.environ):
        if k.startswith("BREADMIND_MESSENGER_"):
            monkeypatch.delenv(k, raising=False)
    cfg = MessengerConfig.from_env()
    assert cfg.session_access_ttl_min == 30
    assert cfg.session_refresh_ttl_days == 30
    assert cfg.invite_ttl_days == 14
    assert cfg.visible_channels_ttl_sec == 300
    assert cfg.rate_limit_tier2 == 50


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("BREADMIND_MESSENGER_RATE_LIMIT_TIER2", "100")
    monkeypatch.setenv("BREADMIND_MESSENGER_INVITE_TTL_DAYS", "7")
    cfg = MessengerConfig.from_env()
    assert cfg.rate_limit_tier2 == 100
    assert cfg.invite_ttl_days == 7


def test_paseto_key_default():
    cfg = MessengerConfig.from_env()
    assert isinstance(cfg.paseto_key_hex, str)
    assert len(cfg.paseto_key_hex) >= 32
