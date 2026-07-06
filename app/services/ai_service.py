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
