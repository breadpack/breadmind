"""Tests for breadmind.kb.redactor."""
from __future__ import annotations

import pytest

from breadmind.kb.redactor import Redactor, SecretDetected


async def test_redact_email_and_restore_roundtrip(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, map_id = await r.redact(
        "ping me at alice@example.com please", session_id="s1"
    )
    assert "alice@example.com" not in masked
    assert "<EMAIL_1>" in masked
    restored = await r.restore(masked, map_id)
    assert "alice@example.com" in restored


async def test_redact_phone(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, _ = await r.redact("call +1-415-555-0132 tonight", session_id="s1")
    assert "+1-415-555-0132" not in masked
    assert "<PHONE_1>" in masked


async def test_redact_slack_user_id(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, _ = await r.redact("ask <@U012ABCDEF> about it", session_id="s1")
    assert "U012ABCDEF" not in masked
    assert "<USER_1>" in masked


async def test_redact_p4_depot_path(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, _ = await r.redact(
        "see //depot/game/client/src/main.cpp line 42", session_id="s1"
    )
    assert "//depot/game/client" not in masked
    assert "<P4_PATH_1>" in masked


async def test_redact_vocab_client_name(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, _ = await r.redact("meeting with Acme Corp tomorrow", session_id="s1")
    assert "Acme Corp" not in masked
    assert "<CLIENT_1>" in masked


async def test_redact_internal_url_keeps_path_only(fake_redis, sample_vocab):
    r = Redactor(
        redis=fake_redis,
        vocab=sample_vocab,
    )
    r.internal_domains = {"corp.example.com"}
    masked, _ = await r.redact(
        "see https://corp.example.com/wiki/spec for details", session_id="s1"
    )
    assert "corp.example.com" not in masked
    assert "<INTERNAL_URL_1>" in masked


async def test_abort_on_api_key(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    with pytest.raises(SecretDetected):
        await r.abort_if_secrets(
            "token sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        )


async def test_abort_on_high_entropy(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    with pytest.raises(SecretDetected):
        await r.abort_if_secrets(
            "x=Zq7!pV9@mR2#kW4$jL8%hN6^bT1&dF3*gY5xZa"
        )


async def test_abort_on_credit_card_luhn(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    with pytest.raises(SecretDetected):
        await r.abort_if_secrets("card 4111 1111 1111 1111 exp 01/29")


async def test_abort_on_ssn(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    with pytest.raises(SecretDetected):
        await r.abort_if_secrets("SSN 123-45-6789")


async def test_restore_unknown_map_id_returns_text_unchanged(
    fake_redis, sample_vocab
):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    out = await r.restore("<EMAIL_1> hello", map_id="missing")
    assert out == "<EMAIL_1> hello"


async def test_ttl_expired_map_returns_masked_text(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    masked, map_id = await r.redact("alice@example.com", session_id="s1")
    await fake_redis.delete(f"redact:map:{map_id}")
    out = await r.restore(masked, map_id)
    assert "alice@example.com" not in out


async def test_safe_text_passes_through(fake_redis, sample_vocab):
    r = Redactor(redis=fake_redis, vocab=sample_vocab)
    await r.abort_if_secrets("just some harmless text about bread.")
    masked, _ = await r.redact("harmless text with no pii", session_id="s1")
    assert masked == "harmless text with no pii"
