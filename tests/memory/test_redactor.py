"""Tests for the PII / credential redactor used by EpisodicRecorder.

Covers Section 13 follow-up: defensive masking of common PII / credential
patterns BEFORE rendered text reaches the LLM via episodic_normalize.j2.
"""

from breadmind.memory.redactor import redact


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------

def test_email_positive_is_masked():
    text = "Contact alice.bob+test@example.co.uk for details."
    out = redact(text)
    assert "alice.bob+test@example.co.uk" not in out
    assert "[EMAIL]" in out


def test_email_negative_keeps_non_email():
    # @-handle and at-symbol-not-followed-by-domain should survive.
    text = "ping @alice in channel, cost is 5@10 each."
    out = redact(text)
    assert out == text  # no email shape -> unchanged
    assert "[EMAIL]" not in out


# ---------------------------------------------------------------------------
# IPv4
# ---------------------------------------------------------------------------

def test_ipv4_positive_is_masked():
    out = redact("connect to 10.0.4.21 for the API")
    assert "10.0.4.21" not in out
    assert "[IPV4]" in out


def test_ipv4_loopback_and_zero_are_kept():
    text = "bind 127.0.0.1 then check 0.0.0.0 fallback"
    out = redact(text)
    # Debuggability: keep loopback / unspecified address as-is.
    assert "127.0.0.1" in out
    assert "0.0.0.0" in out
    assert "[IPV4]" not in out


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def test_jwt_positive_is_masked():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFsaWNlIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    out = redact(f"token={jwt} OK")
    assert jwt not in out
    assert "[JWT]" in out


def test_jwt_negative_keeps_non_jwt():
    # Single base64-ish blob without the eyJ-prefix triple shape is not a JWT.
    text = "checksum=eyJhbGc but no signature here"
    out = redact(text)
    assert out == text
    assert "[JWT]" not in out


# ---------------------------------------------------------------------------
# AWS access key id
# ---------------------------------------------------------------------------

def test_aws_key_positive_is_masked():
    out = redact("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[AWS_KEY]" in out


def test_aws_key_negative_keeps_short_or_lowercase():
    # Lowercase / too-short tokens must not match.
    text = "tag=akia123 region=ap-northeast-2 ref=AKIA"
    out = redact(text)
    assert out == text
    assert "[AWS_KEY]" not in out


# ---------------------------------------------------------------------------
# Bearer-style hex/base64 (only inside Authorization:/Bearer prefix)
# ---------------------------------------------------------------------------

def test_bearer_positive_is_masked():
    text = "Authorization: Bearer abcdef0123456789abcdef0123456789ABCDEF12 next"
    out = redact(text)
    assert "abcdef0123456789abcdef0123456789ABCDEF12" not in out
    assert "[BEARER]" in out


def test_bearer_negative_keeps_bare_hash():
    # A bare 40+char hex string without Authorization/Bearer prefix must
    # NOT be masked (would otherwise eat git SHAs and SRI hashes).
    text = "commit=abcdef0123456789abcdef0123456789ABCDEF12 sha=ok"
    out = redact(text)
    assert out == text
    assert "[BEARER]" not in out


# ---------------------------------------------------------------------------
# Misc / contract
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty():
    assert redact("") == ""


def test_idempotent():
    text = (
        "user a@b.com from 10.0.0.5 wired AKIAIOSFODNN7EXAMPLE "
        "Authorization: Bearer abcdef0123456789abcdef0123456789ABCDEF12 "
        "tok=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    once = redact(text)
    twice = redact(once)
    assert once == twice
    # Sanity: at least one mask token present
    assert "[EMAIL]" in once
