import pytest
from datetime import datetime, timezone
from uuid import UUID
from breadmind.messenger.pagination import (
    encode_cursor, decode_cursor, CursorEnvelope, InvalidCursor,
)


def test_encode_decode_round_trip():
    env = CursorEnvelope(
        created_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
        id=UUID("12345678-1234-5678-1234-567812345678"),
    )
    c = encode_cursor(env)
    decoded = decode_cursor(c)
    assert decoded.created_at == env.created_at
    assert decoded.id == env.id


def test_decode_invalid_raises():
    with pytest.raises(InvalidCursor):
        decode_cursor("garbage")


def test_decode_tampered_raises():
    env = CursorEnvelope(
        created_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
        id=UUID(int=0),
    )
    c = encode_cursor(env)
    tampered = c[:-2] + "AA"
    with pytest.raises(InvalidCursor):
        decode_cursor(tampered)
