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
