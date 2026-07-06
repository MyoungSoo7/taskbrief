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
