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
