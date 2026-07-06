import jwt as pyjwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("password123")
    assert hashed != "password123"
    assert verify_password("password123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_long_password_over_72_bytes_roundtrip():
    # bcrypt는 72바이트 초과 입력에서 ValueError를 낸다. SHA-256 pre-hash로 임의 길이를 지원해야 한다.
    long_pw = "가" * 50  # 150바이트 (bcrypt 72바이트 한계 초과)
    hashed = hash_password(long_pw)
    assert verify_password(long_pw, hashed)
    assert not verify_password("가" * 49, hashed)


def test_access_token_roundtrip():
    token = create_access_token(user_id=42)
    assert decode_token(token) == 42


def test_expired_token_rejected():
    token = create_access_token(user_id=42, expires_minutes=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(token)


def test_tampered_token_rejected():
    token = pyjwt.encode({"sub": "42"}, "different-wrong-secret-" + "y" * 16, algorithm=settings.jwt_algorithm)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(token)
