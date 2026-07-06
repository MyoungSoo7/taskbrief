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
