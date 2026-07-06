import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_session
from app.models import User


def _prehash(password: str) -> bytes:
    """bcrypt의 72바이트 입력 한계를 우회하기 위해 SHA-256으로 먼저 압축한다.

    digest(32바이트)를 base64로 인코딩해 44바이트 고정 길이로 만들어,
    임의 길이 비밀번호를 잘림/오류 없이 지원한다.
    """
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(password), hashed.encode())


def create_access_token(user_id: int, expires_minutes: int | None = None) -> str:
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> int:
    """토큰을 검증하고 user_id를 반환. 실패 시 jwt.InvalidTokenError 계열 예외."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return int(payload["sub"])


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_credentials_error = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "인증 정보가 유효하지 않습니다.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    try:
        user_id = decode_token(token)
    except jwt.InvalidTokenError:
        raise _credentials_error from None
    user = await session.get(User, user_id)
    if user is None:
        raise _credentials_error
    return user
