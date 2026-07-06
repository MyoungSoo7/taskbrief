# TaskBrief 구현 계획 (AI 브리핑 할일 관리 API)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI 기반 할일 관리 REST API에 JWT 멀티유저 인증과 Claude API 기반 일일/주간 AI 브리핑을 구현한다.

**Architecture:** 라우터(HTTP 관심사) → 서비스(비즈니스 로직) → SQLAlchemy 모델 계층 분리. LLM 호출은 `app/services/ai_service.py`에 완전히 격리해 테스트에서 mock으로 대체한다. 브리핑은 fingerprint 기반 DB 캐시로 중복 LLM 호출을 방지한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async + aiosqlite, Alembic, PyJWT + bcrypt, anthropic SDK, pytest + pytest-asyncio + httpx, Docker.

**Spec:** `docs/superpowers/specs/2026-07-06-taskbrief-design.md`

**환경 참고 (모든 태스크 공통):**
- Windows. 명령은 저장소 루트에서 실행. 파이썬/도구는 항상 venv 경로로 직접 호출: `.venv\Scripts\python`, `.venv\Scripts\alembic`
- 테스트 실행: `.venv\Scripts\python -m pytest -v` (특정 파일: `.venv\Scripts\python -m pytest tests/test_auth.py -v`)
- **datetime 규약**: DB에는 항상 **naive UTC**로 저장한다 (SQLite는 timezone을 보존하지 않으므로). timezone 변환은 서비스 계층에서만 수행. API 입력의 aware datetime은 스키마 validator에서 naive UTC로 정규화한다.
- 커밋 메시지는 conventional commits (`feat:`, `test:`, `chore:`, `docs:`)

---

## Chunk 1: 프로젝트 기반 (설정 · DB · 모델 · 마이그레이션)

### Task 1: 의존성과 프로젝트 골격

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `.env.example`
- Create: `app/__init__.py`, `app/core/__init__.py`, `app/models/__init__.py`, `app/schemas/__init__.py`, `app/routers/__init__.py`, `app/services/__init__.py`, `tests/__init__.py`
- Delete: `main.py`, `test_main.http` (PyCharm 템플릿 — `app/main.py`로 대체, `.http` 파일은 Task 14에서 실제 엔드포인트로 재작성)

- [ ] **Step 1: 의존성 파일 작성**

`requirements.txt`:

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic[email]>=2.7
sqlalchemy>=2.0
aiosqlite>=0.20
alembic>=1.13
pydantic-settings>=2.3
PyJWT>=2.9
bcrypt>=4.1
anthropic>=0.40
python-multipart>=0.0.9
```

`requirements-dev.txt`:

```
pytest>=8.0
pytest-asyncio>=0.24
httpx>=0.27
```

`pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
testpaths = tests
```

- [ ] **Step 2: .gitignore와 .env.example 작성**

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.env
*.db
data/
.pytest_cache/
```

`.env.example`:

```
DATABASE_URL=sqlite+aiosqlite:///./taskbrief.db
JWT_SECRET=change-me-to-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=60
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
LLM_TIMEOUT_SECONDS=10
TIMEZONE=Asia/Seoul
```

- [ ] **Step 3: 패키지 골격 생성 + 템플릿 파일 삭제**

빈 `__init__.py`를 위 Files 목록의 7개 위치에 생성한다. 그리고 템플릿 파일 삭제 (최초 커밋 전이라 `git rm`은 거부되므로 `-f` 사용):

```powershell
git rm -f main.py test_main.http
```

- [ ] **Step 4: 의존성 설치 및 확인**

Run: `.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`
Expected: 에러 없이 설치 완료. `.venv\Scripts\python -c "import fastapi, sqlalchemy, jwt, bcrypt, anthropic; print('ok')"` → `ok`

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "chore: 프로젝트 골격과 의존성 구성"
```

### Task 2: 설정 · DB 세션 · 앱 팩토리 (+ 테스트 인프라)

**Files:**
- Create: `app/core/config.py`, `app/db.py`, `app/main.py`
- Test: `tests/conftest.py`, `tests/test_health.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_health.py`:

```python
async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
```

`tests/conftest.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'` (또는 app.main)

- [ ] **Step 3: 구현**

`app/core/config.py`:

```python
from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./taskbrief.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    llm_timeout_seconds: float = 10.0
    timezone: str = "Asia/Seoul"

    @cached_property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
```

`app/db.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """DB 저장용 naive UTC 현재 시각."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session
```

`app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(
    title="TaskBrief",
    description="AI 브리핑 기능이 있는 할일 관리 API",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_health.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```powershell
git add app tests pytest.ini
git commit -m "feat: 설정, async DB 세션, 앱 팩토리와 헬스체크"
```

### Task 3: 도메인 모델과 Alembic 마이그레이션

**Files:**
- Create: `app/models/enums.py`, `app/models/user.py`, `app/models/task.py`, `app/models/briefing.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/` (alembic init), `alembic.ini`
- Test: `tests/test_models.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py`:

```python
from app.models import Briefing, Task, User


async def test_models_create(session_factory):
    async with session_factory() as session:
        user = User(email="a@test.com", hashed_password="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        task = Task(user_id=user.id, title="테스트 할일")
        session.add(task)
        await session.commit()
        await session.refresh(task)

        assert task.priority == "mid"
        assert task.status == "todo"
        assert task.created_at is not None

        briefing = Briefing(
            user_id=user.id, kind="daily",
            content={"summary": "s", "suggestions": [], "urgent_count": 0},
            tasks_fingerprint="abc",
        )
        session.add(briefing)
        await session.commit()
        await session.refresh(briefing)
        assert briefing.content["summary"] == "s"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'User'`

- [ ] **Step 3: 모델 구현**

`app/models/enums.py`:

```python
import enum


class TaskPriority(str, enum.Enum):
    low = "low"
    mid = "mid"
    high = "high"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    doing = "doing"
    done = "done"


class BriefingKind(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
```

`app/models/user.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

`app/models/task.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    priority: Mapped[str] = mapped_column(String(10), default="mid")
    status: Mapped[str] = mapped_column(String(10), default="todo")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
```

`app/models/briefing.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    content: Mapped[dict] = mapped_column(JSON)
    tasks_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

`app/models/__init__.py`:

```python
from app.models.briefing import Briefing
from app.models.enums import BriefingKind, TaskPriority, TaskStatus
from app.models.task import Task
from app.models.user import User

__all__ = ["Briefing", "BriefingKind", "Task", "TaskPriority", "TaskStatus", "User"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Alembic 초기화 및 초기 마이그레이션**

```powershell
.venv\Scripts\alembic init -t async alembic
```

`alembic/env.py`에서 아래 두 곳을 수정:

```python
# (1) 파일 상단 import 구역에 추가
from app.core.config import settings
from app.db import Base
import app.models  # noqa: F401 — autogenerate가 모델을 인식하도록
```

```python
# (2) `config = context.config` 줄 **아래**에 추가 (config가 정의된 후여야 함)
config.set_main_option("sqlalchemy.url", settings.database_url)
```

```python
# (3) target_metadata = None  ← 이 줄을 다음으로 교체
target_metadata = Base.metadata
```

```powershell
.venv\Scripts\alembic revision --autogenerate -m "create users, tasks, briefings"
.venv\Scripts\alembic upgrade head
```

Expected: `alembic/versions/`에 마이그레이션 파일 생성(users/tasks/briefings 테이블 포함 확인), `taskbrief.db` 파일 생성, `.venv\Scripts\alembic current` 출력에 `(head)` 표시

- [ ] **Step 6: Commit**

```powershell
git add app tests alembic alembic.ini
git commit -m "feat: User/Task/Briefing 모델과 초기 마이그레이션"
```

---

## Chunk 2: 인증 (JWT 멀티유저)

### Task 4: 보안 유틸 (해싱 · JWT)

**Files:**
- Create: `app/core/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_security.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 ImportError

- [ ] **Step 3: 구현**

`app/core/security.py`:

```python
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int, expires_minutes: int | None = None) -> str:
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> int:
    """토큰을 검증하고 user_id를 반환. 실패 시 jwt.InvalidTokenError 계열 예외."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return int(payload["sub"])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_security.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add app/core/security.py tests/test_security.py
git commit -m "feat: bcrypt 해싱과 JWT 발급/검증 유틸"
```

### Task 5: 회원가입 · 로그인 엔드포인트

**Files:**
- Create: `app/schemas/user.py`, `app/schemas/auth.py`, `app/routers/auth.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_auth.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_auth.py`:

```python
SIGNUP = {"email": "me@test.com", "password": "password123"}


async def test_signup_returns_201(client):
    res = await client.post("/auth/signup", json=SIGNUP)
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "me@test.com"
    assert "password" not in body and "hashed_password" not in body


async def test_signup_duplicate_email_409(client):
    await client.post("/auth/signup", json=SIGNUP)
    res = await client.post("/auth/signup", json=SIGNUP)
    assert res.status_code == 409


async def test_signup_short_password_422(client):
    res = await client.post("/auth/signup", json={"email": "a@test.com", "password": "short"})
    assert res.status_code == 422


async def test_login_returns_token(client):
    await client.post("/auth/signup", json=SIGNUP)
    res = await client.post(
        "/auth/login",
        data={"username": SIGNUP["email"], "password": SIGNUP["password"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_wrong_password_401(client):
    await client.post("/auth/signup", json=SIGNUP)
    res = await client.post(
        "/auth/login", data={"username": SIGNUP["email"], "password": "wrong-password"}
    )
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_auth.py -v`
Expected: FAIL — 404 (라우터 미등록)

- [ ] **Step 3: 구현**

`app/schemas/user.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime
```

참고: `EmailStr`에 필요한 `email-validator`는 Task 1의 `pydantic[email]` 의존성으로 이미 설치되어 있다.

`app/schemas/auth.py`:

```python
from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

`app/routers/auth.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db import get_session
from app.models import User
from app.schemas.auth import Token
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def signup(payload: UserCreate, session: Annotated[AsyncSession, Depends(get_session)]):
    existing = await session.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    user = await session.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
```

`app/main.py` — import 아래에 추가:

```python
from app.routers import auth

app.include_router(auth.router)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_auth.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add app tests requirements.txt
git commit -m "feat: 회원가입/로그인 엔드포인트 (OAuth2 Password Flow + JWT)"
```

### Task 6: 현재 사용자 의존성 (`get_current_user`)

**Files:**
- Modify: `app/core/security.py` (의존성 추가), `app/routers/auth.py` (`GET /auth/me` — 인증 의존성 검증용 최소 보호 엔드포인트)
- Modify: `tests/conftest.py` (auth_headers 픽스처)
- Test: `tests/test_auth.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/conftest.py`에 픽스처 추가:

```python
@pytest.fixture
async def auth_headers(client):
    await client.post("/auth/signup", json={"email": "me@test.com", "password": "password123"})
    res = await client.post(
        "/auth/login", data={"username": "me@test.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
async def other_auth_headers(client):
    await client.post("/auth/signup", json={"email": "other@test.com", "password": "password123"})
    res = await client.post(
        "/auth/login", data={"username": "other@test.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
```

`tests/test_auth.py`에 추가:

```python
async def test_me_returns_current_user(client, auth_headers):
    res = await client.get("/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "me@test.com"


async def test_me_without_token_401(client):
    res = await client.get("/auth/me")
    assert res.status_code == 401


async def test_me_with_invalid_token_401(client):
    res = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert res.status_code == 401


async def test_me_with_expired_token_401(client, auth_headers):
    from app.core.security import create_access_token

    expired = create_access_token(user_id=1, expires_minutes=-1)
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_auth.py -v`
Expected: 새 테스트 4개 FAIL (404 — /auth/me 없음)

- [ ] **Step 3: 구현**

`app/core/security.py`에 추가:

```python
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User

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
        raise _credentials_error
    user = await session.get(User, user_id)
    if user is None:
        raise _credentials_error
    return user
```

`app/routers/auth.py`에 추가:

```python
from app.core.security import get_current_user
from app.models import User


@router.get("/me", response_model=UserRead)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return user
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: get_current_user 의존성과 /auth/me"
```

---

## Chunk 3: 할일 CRUD

### Task 7: Task 스키마 · 생성 · 목록

**Files:**
- Create: `app/schemas/task.py`, `app/services/task_service.py`, `app/routers/tasks.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_tasks.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tasks.py`:

```python
async def test_create_task_201(client, auth_headers):
    res = await client.post(
        "/tasks",
        json={"title": "보고서 작성", "priority": "high", "due_date": "2026-07-08T18:00:00+09:00"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "보고서 작성"
    assert body["status"] == "todo"
    # aware 입력은 naive UTC로 정규화되어 저장된다 (+09:00 18시 → UTC 09시)
    assert body["due_date"] == "2026-07-08T09:00:00"


async def test_create_task_requires_auth(client):
    res = await client.post("/tasks", json={"title": "x"})
    assert res.status_code == 401


async def test_create_task_empty_title_422(client, auth_headers):
    res = await client.post("/tasks", json={"title": ""}, headers=auth_headers)
    assert res.status_code == 422


async def test_list_tasks_returns_own_tasks_only(client, auth_headers, other_auth_headers):
    await client.post("/tasks", json={"title": "내 할일"}, headers=auth_headers)
    await client.post("/tasks", json={"title": "남의 할일"}, headers=other_auth_headers)

    res = await client.get("/tasks", headers=auth_headers)
    assert res.status_code == 200
    titles = [t["title"] for t in res.json()]
    assert titles == ["내 할일"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_tasks.py -v`
Expected: FAIL (404 — 라우터 없음)

- [ ] **Step 3: 구현**

`app/schemas/task.py`:

```python
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TaskPriority, TaskStatus


def _to_utc_naive(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    priority: TaskPriority = TaskPriority.mid

    _normalize_due = field_validator("due_date")(_to_utc_naive)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None

    _normalize_due = field_validator("due_date")(_to_utc_naive)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    due_date: datetime | None
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
```

`app/services/task_service.py`:

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.models.enums import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate


async def create_task(session: AsyncSession, user_id: int, data: TaskCreate) -> Task:
    task = Task(user_id=user_id, **data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    user_id: int,
    status: TaskStatus | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Task.status == status.value)
    if due_before is not None:
        stmt = stmt.where(Task.due_date != None, Task.due_date <= due_before)  # noqa: E711
    if due_after is not None:
        stmt = stmt.where(Task.due_date != None, Task.due_date >= due_after)  # noqa: E711
    stmt = stmt.order_by(Task.id).offset(offset).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_task(session: AsyncSession, user_id: int, task_id: int) -> Task | None:
    """본인 소유가 아니면 None (라우터에서 404 — 존재 여부 비노출)."""
    return await session.scalar(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )


async def update_task(session: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task: Task) -> None:
    await session.delete(task)
    await session.commit()
```

참고: enum 값은 `data.model_dump()`에서 str enum이므로 `String(10)` 컬럼에 그대로 저장된다 (`TaskPriority.high`는 `"high"`로 직렬화됨 — `model_dump(mode="python")`도 str enum이라 문자열 비교가 성립).

`app/routers/tasks.py`:

```python
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db import get_session
from app.models import User
from app.models.enums import TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskRead)
async def create_task(payload: TaskCreate, user: UserDep, session: SessionDep):
    return await task_service.create_task(session, user.id, payload)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    user: UserDep,
    session: SessionDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await task_service.list_tasks(
        session, user.id, status_filter, due_before, due_after, offset, limit
    )
```

`app/main.py` — 라우터 등록 수정:

```python
from app.routers import auth, tasks

app.include_router(auth.router)
app.include_router(tasks.router)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_tasks.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: 할일 생성/목록 엔드포인트와 서비스 계층"
```

### Task 8: 단건 조회 · 수정 · 삭제 + 데이터 격리

**Files:**
- Modify: `app/routers/tasks.py`
- Test: `tests/test_tasks.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_tasks.py`에 추가:

```python
async def _create(client, headers, title="할일"):
    res = await client.post("/tasks", json={"title": title}, headers=headers)
    return res.json()["id"]


async def test_get_task(client, auth_headers):
    task_id = await _create(client, auth_headers)
    res = await client.get(f"/tasks/{task_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == task_id


async def test_patch_task_updates_fields(client, auth_headers):
    task_id = await _create(client, auth_headers)
    res = await client.patch(
        f"/tasks/{task_id}", json={"status": "doing", "priority": "high"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "doing"
    assert res.json()["priority"] == "high"


async def test_delete_task_204_then_404(client, auth_headers):
    task_id = await _create(client, auth_headers)
    res = await client.delete(f"/tasks/{task_id}", headers=auth_headers)
    assert res.status_code == 204
    res = await client.get(f"/tasks/{task_id}", headers=auth_headers)
    assert res.status_code == 404


async def test_other_users_task_is_404(client, auth_headers, other_auth_headers):
    task_id = await _create(client, other_auth_headers, "남의 할일")
    assert (await client.get(f"/tasks/{task_id}", headers=auth_headers)).status_code == 404
    assert (
        await client.patch(f"/tasks/{task_id}", json={"title": "탈취"}, headers=auth_headers)
    ).status_code == 404
    assert (await client.delete(f"/tasks/{task_id}", headers=auth_headers)).status_code == 404
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_tasks.py -v`
Expected: 새 테스트 4개 FAIL (405 또는 404)

- [ ] **Step 3: 구현** — `app/routers/tasks.py`에 추가:

```python
async def _get_or_404(session: AsyncSession, user_id: int, task_id: int):
    task = await task_service.get_task(session, user_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "할일을 찾을 수 없습니다.")
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: int, user: UserDep, session: SessionDep):
    return await _get_or_404(session, user.id, task_id)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(task_id: int, payload: TaskUpdate, user: UserDep, session: SessionDep):
    task = await _get_or_404(session, user.id, task_id)
    return await task_service.update_task(session, task, payload)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, user: UserDep, session: SessionDep):
    task = await _get_or_404(session, user.id, task_id)
    await task_service.delete_task(session, task)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_tasks.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: 할일 단건 조회/수정/삭제와 사용자 격리(404)"
```

### Task 9: 필터와 페이지네이션

**Files:**
- Test: `tests/test_tasks.py` (추가 — 구현은 Task 7에서 완료, 여기서 동작 검증)

- [ ] **Step 1: 테스트 작성** — `tests/test_tasks.py`에 추가:

```python
async def test_filter_by_status(client, auth_headers):
    t1 = await _create(client, auth_headers, "진행중 건")
    await _create(client, auth_headers, "미착수 건")
    await client.patch(f"/tasks/{t1}", json={"status": "doing"}, headers=auth_headers)

    res = await client.get("/tasks", params={"status": "doing"}, headers=auth_headers)
    assert [t["title"] for t in res.json()] == ["진행중 건"]


async def test_filter_by_due_range(client, auth_headers):
    await client.post(
        "/tasks", json={"title": "이른 마감", "due_date": "2026-07-07T00:00:00"}, headers=auth_headers
    )
    await client.post(
        "/tasks", json={"title": "늦은 마감", "due_date": "2026-07-20T00:00:00"}, headers=auth_headers
    )
    await client.post("/tasks", json={"title": "마감 없음"}, headers=auth_headers)

    res = await client.get(
        "/tasks",
        params={"due_after": "2026-07-10T00:00:00", "due_before": "2026-07-31T00:00:00"},
        headers=auth_headers,
    )
    assert [t["title"] for t in res.json()] == ["늦은 마감"]


async def test_pagination(client, auth_headers):
    for i in range(5):
        await _create(client, auth_headers, f"할일 {i}")

    res = await client.get("/tasks", params={"offset": 2, "limit": 2}, headers=auth_headers)
    assert [t["title"] for t in res.json()] == ["할일 2", "할일 3"]


async def test_limit_over_100_is_422(client, auth_headers):
    res = await client.get("/tasks", params={"limit": 101}, headers=auth_headers)
    assert res.status_code == 422


async def test_invalid_status_filter_is_422(client, auth_headers):
    res = await client.get("/tasks", params={"status": "unknown"}, headers=auth_headers)
    assert res.status_code == 422
```

- [ ] **Step 2: 테스트 통과 확인 (구현은 이미 존재)**

Run: `.venv\Scripts\python -m pytest tests/test_tasks.py -v`
Expected: 전부 PASS. 실패하면 Task 7의 `list_tasks` 필터 로직을 수정한다.

- [ ] **Step 3: Commit**

```powershell
git add tests
git commit -m "test: 할일 필터/페이지네이션 경계 검증"
```

---

## Chunk 4: AI 브리핑

### Task 10: `ai_service` — LLM 호출 격리 계층

**Files:**
- Create: `app/services/ai_service.py`
- Test: `tests/test_ai_service.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ai_service.py`:

```python
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Task
from app.services import ai_service
from app.services.ai_service import AIBriefingResult, BriefingConfigError, BriefingGenerationError

TASKS = [Task(id=1, user_id=1, title="보고서", status="todo", priority="high")]
TODAY = date(2026, 7, 6)


def _fake_client(response_text: str):
    """messages.create가 response_text를 돌려주는 가짜 anthropic 클라이언트."""
    message = SimpleNamespace(content=[SimpleNamespace(text=response_text)])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))
    return client


async def test_no_api_key_raises_config_error(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "anthropic_api_key", "")
    with pytest.raises(BriefingConfigError):
        await ai_service.generate_briefing(TASKS, "daily", TODAY)


async def test_valid_json_response_parsed(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "anthropic_api_key", "test-key")
    fake = _fake_client('{"summary": "바쁜 하루입니다.", "suggestions": ["보고서부터 시작"]}')
    with patch.object(ai_service, "_make_client", return_value=fake):
        result = await ai_service.generate_briefing(TASKS, "daily", TODAY)
    assert isinstance(result, AIBriefingResult)
    assert result.summary == "바쁜 하루입니다."
    assert result.suggestions == ["보고서부터 시작"]


async def test_fenced_json_response_parsed(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "anthropic_api_key", "test-key")
    fake = _fake_client('```json\n{"summary": "s", "suggestions": []}\n```')
    with patch.object(ai_service, "_make_client", return_value=fake):
        result = await ai_service.generate_briefing(TASKS, "daily", TODAY)
    assert result.summary == "s"


async def test_invalid_json_raises_generation_error(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "anthropic_api_key", "test-key")
    fake = _fake_client("JSON이 아닌 답변")
    with patch.object(ai_service, "_make_client", return_value=fake):
        with pytest.raises(BriefingGenerationError):
            await ai_service.generate_briefing(TASKS, "daily", TODAY)


async def test_missing_required_key_raises_generation_error(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "anthropic_api_key", "test-key")
    fake = _fake_client('{"summary": "제안 누락"}')
    with patch.object(ai_service, "_make_client", return_value=fake):
        with pytest.raises(BriefingGenerationError):
            await ai_service.generate_briefing(TASKS, "daily", TODAY)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_ai_service.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`app/services/ai_service.py`:

```python
import json
from datetime import date

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.models import Task


class BriefingConfigError(Exception):
    """API 키 미설정 등 구성 문제 — 재시도해도 소용없음."""


class BriefingGenerationError(Exception):
    """LLM 호출 실패/타임아웃/파싱 실패 — 재시도 가치 있음."""


class AIBriefingResult(BaseModel):
    summary: str
    suggestions: list[str]


_SYSTEM = (
    "당신은 할일 관리 비서입니다. 사용자의 할일 목록을 바탕으로 간결한 한국어 브리핑을 작성합니다. "
    "반드시 JSON 객체 하나만 출력하고, 그 외 텍스트는 출력하지 마세요."
)


def _make_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # 재시도는 briefing_service에서 1회 수행
    )


def _build_prompt(tasks: list[Task], kind: str, today: date) -> str:
    period = "오늘" if kind == "daily" else "이번 주"
    lines = []
    for t in tasks:
        due = f" (마감: {t.due_date:%Y-%m-%d %H:%M} UTC)" if t.due_date else ""
        lines.append(f"- [{t.status}/{t.priority}] {t.title}{due}")
    return (
        f"오늘 날짜: {today:%Y-%m-%d}\n"
        f"{period}의 할일 목록:\n" + "\n".join(lines) + "\n\n"
        f"위 할일을 바탕으로 {period}의 브리핑을 작성하세요. 우선순위와 마감 임박 건을 짚어주세요.\n"
        '다음 JSON 스키마로만 답하세요: {"summary": "2~4문장 브리핑", "suggestions": ["추천 행동 1~3개"]}'
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.removesuffix("```")
    return text.strip()


async def generate_briefing(tasks: list[Task], kind: str, today: date) -> AIBriefingResult:
    if not settings.anthropic_api_key:
        raise BriefingConfigError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    client = _make_client()
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_prompt(tasks, kind, today)}],
        )
        text = _strip_fences(response.content[0].text)
        return AIBriefingResult.model_validate(json.loads(text))
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValidationError,
        IndexError,
        AttributeError,  # content 블록에 .text가 없는 경우도 503 계약 유지
    ) as exc:
        raise BriefingGenerationError(str(exc)) from exc
```

참고: 타임아웃(`anthropic.APITimeoutError`)은 `anthropic.APIError`의 하위 예외라 위 except에 포함된다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_ai_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: ai_service — Claude 호출 격리, JSON 파싱/검증, 에러 분류"
```

### Task 11: `briefing_service` — 대상 선정 · fingerprint · urgent_count 헬퍼

**Files:**
- Create: `app/schemas/briefing.py`, `app/services/briefing_service.py` (헬퍼 부분)
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_briefing_service.py`:

```python
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models import Task
from app.services import briefing_service


@pytest.fixture(autouse=True)
def _pin_kst(monkeypatch):
    """개발자 .env의 TIMEZONE 값과 무관하게 KST 기준으로 검증한다."""
    monkeypatch.setattr(
        briefing_service, "settings", SimpleNamespace(tzinfo=ZoneInfo("Asia/Seoul"))
    )


def _task(**kw) -> Task:
    defaults = dict(id=1, user_id=1, title="t", status="todo", priority="mid", due_date=None)
    defaults.update(kw)
    return Task(**defaults)


def test_fingerprint_is_order_insensitive():
    a = _task(id=1, title="a")
    b = _task(id=2, title="b")
    assert briefing_service._fingerprint([a, b]) == briefing_service._fingerprint([b, a])


def test_fingerprint_changes_when_status_changes():
    fp1 = briefing_service._fingerprint([_task(status="todo")])
    fp2 = briefing_service._fingerprint([_task(status="doing")])
    assert fp1 != fp2


def test_day_bounds_are_kst_midnight_in_utc():
    # KST 2026-07-06 00:00 == UTC 2026-07-05 15:00
    start, end = briefing_service._day_bounds(date(2026, 7, 6))
    assert start == datetime(2026, 7, 5, 15, 0)
    assert end == datetime(2026, 7, 6, 15, 0)


def test_week_bounds_start_monday():
    # 2026-07-06은 월요일
    start, end = briefing_service._week_bounds(date(2026, 7, 8))  # 수요일 기준
    assert start == datetime(2026, 7, 5, 15, 0)  # 월요일 KST 자정 == UTC 일요일 15시
    assert end == datetime(2026, 7, 12, 15, 0)


def test_urgent_count_counts_due_within_window():
    urgent_end = datetime(2026, 7, 9, 15, 0)  # today(7/6)+3일의 KST 자정 경계(UTC)
    tasks = [
        _task(id=1, due_date=datetime(2026, 7, 7, 3, 0)),   # 3일 이내 → urgent
        _task(id=2, due_date=datetime(2026, 7, 1, 0, 0)),   # 이미 지남 → urgent
        _task(id=3, due_date=datetime(2026, 7, 20, 0, 0)),  # 먼 미래 → not urgent
        _task(id=4, due_date=None, status="doing"),          # 마감 없음 → not urgent
    ]
    assert briefing_service._urgent_count(tasks, urgent_end) == 2
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_briefing_service.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`app/schemas/briefing.py`:

```python
from datetime import datetime

from pydantic import BaseModel


class BriefingRead(BaseModel):
    summary: str
    urgent_count: int
    suggestions: list[str]
    generated_at: datetime
    cached: bool
```

`app/services/briefing_service.py` (헬퍼 — 오케스트레이션은 Task 12에서 추가):

```python
import hashlib
from datetime import date, datetime, time, timedelta, timezone

from app.core.config import settings
from app.models import Task

URGENT_WINDOW_DAYS = 3  # 스펙: "마감 임박" = 3일 이내

EMPTY_SUMMARY = {
    "daily": "오늘은 등록된 할일이 없어요.",
    "weekly": "이번 주에는 등록된 할일이 없어요.",
}


def _today() -> date:
    return datetime.now(settings.tzinfo).date()


def _to_utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """로컬(설정 timezone) 기준 하루의 [시작, 끝) — naive UTC로 반환."""
    start = datetime.combine(d, time.min, tzinfo=settings.tzinfo)
    return _to_utc_naive(start), _to_utc_naive(start + timedelta(days=1))


def _week_bounds(d: date) -> tuple[datetime, datetime]:
    """d가 속한 주(월~일)의 [시작, 끝) — naive UTC로 반환."""
    monday = d - timedelta(days=d.weekday())
    start = datetime.combine(monday, time.min, tzinfo=settings.tzinfo)
    return _to_utc_naive(start), _to_utc_naive(start + timedelta(days=7))


def _urgent_end(today: date) -> datetime:
    """urgent 판정 상한: today+3일의 로컬 자정 경계 (naive UTC)."""
    return _day_bounds(today + timedelta(days=URGENT_WINDOW_DAYS))[1]


def _local_date(utc_naive: datetime) -> date:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(settings.tzinfo).date()


def _fingerprint(tasks: list[Task]) -> str:
    parts = sorted(
        f"{t.id}:{t.status}:{t.due_date}:{t.priority}:{t.title}" for t in tasks
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _urgent_count(tasks: list[Task], urgent_end: datetime) -> int:
    return sum(1 for t in tasks if t.due_date is not None and t.due_date < urgent_end)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest tests/test_briefing_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: 브리핑 헬퍼 — KST 경계 계산, fingerprint, urgent_count"
```

### Task 12: 브리핑 오케스트레이션 · 캐싱 · 라우터

**Files:**
- Modify: `app/services/briefing_service.py` (오케스트레이션 추가)
- Create: `app/routers/briefing.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_briefing.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_briefing.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.services import briefing_service
from app.services.ai_service import AIBriefingResult, BriefingConfigError, BriefingGenerationError

AI_RESULT = AIBriefingResult(summary="바쁜 하루입니다.", suggestions=["보고서부터"])


def _mock_ai(**kwargs):
    """briefing_service가 참조하는 ai_service.generate_briefing을 mock."""
    return patch.object(
        briefing_service.ai_service, "generate_briefing", AsyncMock(**kwargs)
    )


async def test_daily_briefing_generates_and_computes_urgent(client, auth_headers):
    await client.post(
        "/tasks", json={"title": "긴급 건", "due_date": "2100-01-01T00:00:00"}, headers=auth_headers
    )
    # 마감이 먼 미래(2100년)인 할일은 daily 대상에서 빠지므로, doing 상태 건도 하나 만든다
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(
        f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers
    )

    with _mock_ai(return_value=AI_RESULT) as mocked:
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == "바쁜 하루입니다."
    assert body["cached"] is False
    assert body["urgent_count"] == 0  # 진행 건은 마감이 없으므로 urgent 아님
    mocked.assert_awaited_once()


async def test_daily_includes_todo_due_within_3_days(client, auth_headers):
    # 스펙의 핵심 daily 규칙: todo이면서 마감 3일 이내 → 대상 포함 + urgent 집계
    due = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    await client.post(
        "/tasks", json={"title": "임박 건", "due_date": due.isoformat()}, headers=auth_headers
    )

    with _mock_ai(return_value=AI_RESULT) as mocked:
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["urgent_count"] == 1
    mocked.assert_awaited_once()  # 대상이 있으므로 LLM 호출됨


async def test_second_call_hits_cache(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(return_value=AI_RESULT) as mocked:
        first = await client.get("/briefing/daily", headers=auth_headers)
        second = await client.get("/briefing/daily", headers=auth_headers)

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["summary"] == "바쁜 하루입니다."
    mocked.assert_awaited_once()  # 두 번째 호출은 LLM을 부르지 않음


async def test_task_change_invalidates_cache(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    task_id = res.json()["id"]
    await client.patch(f"/tasks/{task_id}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(return_value=AI_RESULT) as mocked:
        await client.get("/briefing/daily", headers=auth_headers)
        await client.patch(f"/tasks/{task_id}", json={"title": "이름 변경"}, headers=auth_headers)
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.json()["cached"] is False
    assert mocked.await_count == 2


async def test_no_tasks_returns_fixed_message_without_llm(client, auth_headers):
    with _mock_ai(return_value=AI_RESULT) as mocked:
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["summary"] == "오늘은 등록된 할일이 없어요."
    assert res.json()["urgent_count"] == 0
    mocked.assert_not_awaited()


async def test_generation_failure_retries_once_then_503(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(side_effect=BriefingGenerationError("boom")) as mocked:
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.status_code == 503
    assert mocked.await_count == 2  # 1회 재시도


async def test_missing_api_key_503_without_retry(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(side_effect=BriefingConfigError("no key")) as mocked:
        res = await client.get("/briefing/daily", headers=auth_headers)

    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]
    mocked.assert_awaited_once()  # 구성 오류는 재시도하지 않음


async def test_weekly_briefing_works(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(return_value=AI_RESULT):
        res = await client.get("/briefing/weekly", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["summary"] == "바쁜 하루입니다."


async def test_weekly_no_tasks_fixed_message_without_llm(client, auth_headers):
    with _mock_ai(return_value=AI_RESULT) as mocked:
        res = await client.get("/briefing/weekly", headers=auth_headers)

    assert res.json()["summary"] == "이번 주에는 등록된 할일이 없어요."
    mocked.assert_not_awaited()


async def test_briefing_requires_auth(client):
    assert (await client.get("/briefing/daily")).status_code == 401
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python -m pytest tests/test_briefing.py -v`
Expected: FAIL (404 — 라우터 없음)

- [ ] **Step 3: 구현**

`app/services/briefing_service.py`에 추가 (import 구역과 파일 끝):

```python
from datetime import date, datetime, time, timedelta, timezone  # 기존 import 유지

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Briefing
from app.schemas.briefing import BriefingRead
from app.services import ai_service


async def _target_tasks(
    session: AsyncSession, user_id: int, kind: str, today: date
) -> list[Task]:
    base = select(Task).where(Task.user_id == user_id, Task.status != "done")
    if kind == "daily":
        # doing 상태이거나, 마감이 3일 이내인 할일.
        # 의도적 결정: 마감이 이미 지난 할일도 포함한다 (아직 처리해야 할 일이므로).
        cond = or_(Task.status == "doing", Task.due_date < _urgent_end(today))
    else:
        # 의도적 결정: 마감 없는 doing 할일도 주간 브리핑 대상에 포함한다.
        week_start, week_end = _week_bounds(today)
        cond = or_(
            Task.status == "doing",
            (Task.due_date >= week_start) & (Task.due_date < week_end),
        )
    stmt = base.where(cond).order_by(Task.due_date.is_(None), Task.due_date, Task.id)
    return list((await session.scalars(stmt)).all())


async def _all_open_tasks(session: AsyncSession, user_id: int) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user_id, Task.status != "done")
    return list((await session.scalars(stmt)).all())


async def _latest_briefing(
    session: AsyncSession, user_id: int, kind: str
) -> Briefing | None:
    stmt = (
        select(Briefing)
        .where(Briefing.user_id == user_id, Briefing.kind == kind)
        .order_by(Briefing.created_at.desc(), Briefing.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_briefing(session: AsyncSession, user_id: int, kind: str) -> BriefingRead:
    """브리핑 조회. 캐시 유효 규칙: 같은 로컬 날짜 + 같은 fingerprint (daily/weekly 동일).

    실패 시 ai_service.BriefingGenerationError(1회 재시도 후) 또는
    ai_service.BriefingConfigError(재시도 없음)를 전파한다 — 라우터에서 503 처리.

    urgent_count는 스펙 §5 정의 그대로 "마감 3일 이내(지난 것 포함) 미완료 할일 수"를
    kind와 무관하게 전체 미완료 할일 기준으로 계산한다 — daily/weekly 응답이 항상 일치.
    """
    today = _today()
    urgent = _urgent_count(await _all_open_tasks(session, user_id), _urgent_end(today))
    tasks = await _target_tasks(session, user_id, kind, today)

    if not tasks:
        return BriefingRead(
            summary=EMPTY_SUMMARY[kind],
            urgent_count=urgent,
            suggestions=[],
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            cached=False,
        )

    fingerprint = _fingerprint(tasks)
    cached = await _latest_briefing(session, user_id, kind)
    if (
        cached is not None
        and cached.tasks_fingerprint == fingerprint
        and _local_date(cached.created_at) == today
    ):
        content = cached.content
        return BriefingRead(
            summary=content["summary"],
            urgent_count=urgent,  # 캐시 히트여도 항상 최신 계산값 (target 밖 할일 변화 반영)
            suggestions=content["suggestions"],
            generated_at=cached.created_at,
            cached=True,
        )

    last_error: ai_service.BriefingGenerationError | None = None
    for _ in range(2):  # 최초 1회 + 재시도 1회
        try:
            result = await ai_service.generate_briefing(tasks, kind, today)
            break
        except ai_service.BriefingGenerationError as exc:
            last_error = exc
    else:
        raise last_error

    content = {
        "summary": result.summary,
        "suggestions": result.suggestions,
        "urgent_count": urgent,
    }
    row = Briefing(
        user_id=user_id, kind=kind, content=content, tasks_fingerprint=fingerprint
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return BriefingRead(
        summary=result.summary,
        urgent_count=urgent,
        suggestions=result.suggestions,
        generated_at=row.created_at,
        cached=False,
    )
```

`app/routers/briefing.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db import get_session
from app.models import User
from app.schemas.briefing import BriefingRead
from app.services import briefing_service
from app.services.ai_service import BriefingConfigError, BriefingGenerationError

router = APIRouter(prefix="/briefing", tags=["briefing"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


async def _briefing_or_503(session: AsyncSession, user_id: int, kind: str) -> BriefingRead:
    try:
        return await briefing_service.get_briefing(session, user_id, kind)
    except BriefingConfigError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI 기능이 설정되지 않았습니다. 서버에 ANTHROPIC_API_KEY를 설정해주세요.",
        )
    except BriefingGenerationError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI 브리핑 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )


@router.get("/daily", response_model=BriefingRead)
async def daily_briefing(user: UserDep, session: SessionDep):
    return await _briefing_or_503(session, user.id, "daily")


@router.get("/weekly", response_model=BriefingRead)
async def weekly_briefing(user: UserDep, session: SessionDep):
    return await _briefing_or_503(session, user.id, "weekly")
```

`app/main.py` — 라우터 등록 수정:

```python
from app.routers import auth, briefing, tasks

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(briefing.router)
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `.venv\Scripts\python -m pytest -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```powershell
git add app tests
git commit -m "feat: AI 브리핑 엔드포인트 — 캐싱, 재시도, 503 처리"
```

---

## Chunk 5: 실행 환경과 문서

### Task 13: Docker

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`

- [ ] **Step 1: Dockerfile 작성**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

`.dockerignore`:

```
.venv/
.git/
__pycache__/
*.db
.env
tests/
docs/
data/
```

- [ ] **Step 2: docker-compose.yml 작성**

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      DATABASE_URL: sqlite+aiosqlite:////app/data/taskbrief.db
    volumes:
      - ./data:/app/data
```

- [ ] **Step 3: 빌드/기동 확인 (Docker가 설치된 경우)**

compose가 `env_file: .env`를 참조하므로 먼저 `.env`가 없으면 생성한다:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Run: `docker compose up --build -d`, 이후 `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`. 확인 후 `docker compose down`.
Docker 미설치 환경이면 이 단계는 건너뛰고 커밋 메시지에 "빌드 미검증" 명시.

- [ ] **Step 4: Commit**

```powershell
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "chore: Docker 실행 환경"
```

### Task 14: README와 HTTP 요청 예제

**Files:**
- Create: `README.md`, `requests.http`

- [ ] **Step 1: README.md 작성** — 아래 섹션을 실제 내용으로 채운다:

1. **프로젝트 소개** — TaskBrief 한 줄 소개 + 핵심 기능(JWT 멀티유저, 할일 CRUD, AI 일일/주간 브리핑, fingerprint 캐싱)
2. **아키텍처** — 계층 구조 다이어그램(텍스트), `ai_service` 격리 설계 의도, 브리핑 데이터 흐름(스펙 6절 요약)
3. **기술 스택** — 스펙 2절 표 재사용
4. **실행 방법** — 로컬(venv + alembic upgrade head + uvicorn), Docker(`docker compose up --build`), `.env.example` 복사 안내
5. **API 개요** — 엔드포인트 표 + `/docs` (Swagger UI) 안내
6. **테스트** — `python -m pytest -v`, LLM은 mock이므로 API 키 없이 전체 통과
7. **설계 결정** — 캐시 규칙(같은 날+fingerprint), urgent 기준(3일), 타인 리소스 404 이유, naive UTC 저장 규약, 시간대(Asia/Seoul)
8. **확장 계획** — 리프레시 토큰, PostgreSQL 전환(설정 한 줄), SSE 스트리밍, CI

- [ ] **Step 2: requests.http 작성** — 수동 테스트용 실제 요청 모음:

```http
### 헬스체크
GET http://127.0.0.1:8000/health

### 회원가입
POST http://127.0.0.1:8000/auth/signup
Content-Type: application/json

{"email": "me@test.com", "password": "password123"}

### 로그인 (응답의 access_token을 아래 @token에 복사)
POST http://127.0.0.1:8000/auth/login
Content-Type: application/x-www-form-urlencoded

username=me@test.com&password=password123

### 이후 요청 공통 변수
@token = PASTE_ACCESS_TOKEN_HERE

### 할일 생성
POST http://127.0.0.1:8000/tasks
Authorization: Bearer {{token}}
Content-Type: application/json

{"title": "보고서 작성", "priority": "high", "due_date": "2026-07-08T18:00:00+09:00"}

### 할일 목록
GET http://127.0.0.1:8000/tasks?status=todo
Authorization: Bearer {{token}}

### 일일 브리핑
GET http://127.0.0.1:8000/briefing/daily
Authorization: Bearer {{token}}

### 주간 브리핑
GET http://127.0.0.1:8000/briefing/weekly
Authorization: Bearer {{token}}
```

- [ ] **Step 3: Commit**

```powershell
git add README.md requests.http
git commit -m "docs: README와 HTTP 요청 예제"
```

### Task 15: 최종 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트**

Run: `.venv\Scripts\python -m pytest -v`
Expected: 전부 PASS, 실패 0

- [ ] **Step 2: 서버 기동 스모크 테스트**

`.env`가 없으면 `.env.example`을 복사해 생성(`Copy-Item .env.example .env`). 그 후:

Run (백그라운드): `.venv\Scripts\python -m uvicorn app.main:app --port 8000`
확인: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`, `http://127.0.0.1:8000/docs` 응답 200
브리핑 수동 확인(선택): `.env`에 실제 `ANTHROPIC_API_KEY`가 있으면 requests.http 플로우로 `/briefing/daily` 1회 호출해 실제 LLM 응답 확인. 키가 없으면 503 + 설정 안내 메시지가 오는지 확인 (이것도 스펙 동작).
확인 후 서버 종료.

- [ ] **Step 3: 미커밋 변경 확인 및 마무리 커밋**

Run: `git status`
Expected: clean (남은 변경이 있으면 적절한 메시지로 커밋)
