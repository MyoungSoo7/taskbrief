import jwt as pyjwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("password123")
    assert hashed != "password123"
    assert verify_password("password123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(user_id=42)
    assert decode_token(token) == 42


def test_expired_token_rejected():
    token = create_access_token(user_id=42, expires_minutes=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(token)


def test_tampered_token_rejected():
    token = pyjwt.encode({"sub": "42"}, "wrong-secret", algorithm=settings.jwt_algorithm)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(token)
