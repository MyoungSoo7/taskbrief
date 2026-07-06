import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db import Base, get_session
from app.main import app


@pytest.fixture(autouse=True)
def _strong_jwt_secret(monkeypatch):
    """테스트에서 RFC 7518 권장 길이(32바이트+)의 시크릿을 써 JWT 서명 키 길이 경고를 없앤다."""
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)


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
