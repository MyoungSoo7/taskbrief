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
    assert body["urgent_count"] == 0  # 진행 건은 마감이 없고, 긴급 건은 2100년(3일 밖)
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
    mocked.assert_awaited_once()


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


async def test_weekly_no_tasks_fixed_message_without_llm(client, auth_headers):
    with _mock_ai(return_value=AI_RESULT) as mocked:
        res = await client.get("/briefing/weekly", headers=auth_headers)

    assert res.json()["summary"] == "이번 주에는 등록된 할일이 없어요."
    mocked.assert_not_awaited()


async def test_weekly_briefing_works(client, auth_headers):
    res = await client.post("/tasks", json={"title": "진행 건"}, headers=auth_headers)
    await client.patch(f"/tasks/{res.json()['id']}", json={"status": "doing"}, headers=auth_headers)

    with _mock_ai(return_value=AI_RESULT):
        res = await client.get("/briefing/weekly", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["summary"] == "바쁜 하루입니다."


async def test_briefing_requires_auth(client):
    assert (await client.get("/briefing/daily")).status_code == 401
