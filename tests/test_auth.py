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
