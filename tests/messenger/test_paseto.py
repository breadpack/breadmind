import pytest
from uuid import uuid4
from breadmind.messenger.auth.paseto import (
    encode_access_token, decode_access_token, encode_refresh_token, decode_refresh_token,
    PasetoError, AccessClaims,
)

KEY = "00" * 32  # 32 bytes hex


def test_access_token_round_trip():
    wid = uuid4()
    uid = uuid4()
    token = encode_access_token(KEY, workspace_id=wid, user_id=uid, role="member", ttl_min=30)
    claims = decode_access_token(KEY, token)
    assert claims.workspace_id == wid
    assert claims.user_id == uid
    assert claims.role == "member"


def test_access_token_expired_raises():
    wid, uid = uuid4(), uuid4()
    token = encode_access_token(KEY, workspace_id=wid, user_id=uid, role="member", ttl_min=-1)
    with pytest.raises(PasetoError, match="expired"):
        decode_access_token(KEY, token)


def test_access_token_wrong_key_raises():
    token = encode_access_token(KEY, workspace_id=uuid4(), user_id=uuid4(), role="member", ttl_min=30)
    with pytest.raises(PasetoError):
        decode_access_token("aa" * 32, token)


def test_refresh_token_round_trip():
    sid = uuid4()
    token = encode_refresh_token(KEY, session_id=sid, ttl_days=30)
    parsed = decode_refresh_token(KEY, token)
    assert parsed == sid


def test_invalid_key_length_raises():
    with pytest.raises(PasetoError, match="32 bytes"):
        encode_access_token("00" * 16, workspace_id=uuid4(), user_id=uuid4(), role="member", ttl_min=30)


def test_kind_mismatch_raises():
    sid = uuid4()
    refresh = encode_refresh_token(KEY, session_id=sid, ttl_days=30)
    with pytest.raises(PasetoError, match="not an access token"):
        decode_access_token(KEY, refresh)
