import hashlib
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Briefing, Task
from app.schemas.briefing import BriefingRead
from app.services import ai_service

URGENT_WINDOW_DAYS = 3  # 스펙: "마감 임박" = 3일 이내

EMPTY_SUMMARY = {
    "daily": "오늘은 등록된 할일이 없어요.",
    "weekly": "이번 주에는 등록된 할일이 없어요.",
}


def _today() -> date:
    return datetime.now(settings.tzinfo).date()


def _to_utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


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
    return utc_naive.replace(tzinfo=UTC).astimezone(settings.tzinfo).date()


def _fingerprint(tasks: list[Task]) -> str:
    parts = sorted(f"{t.id}:{t.status}:{t.due_date}:{t.priority}:{t.title}" for t in tasks)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _urgent_count(tasks: list[Task], urgent_end: datetime) -> int:
    return sum(1 for t in tasks if t.due_date is not None and t.due_date < urgent_end)


async def _target_tasks(session: AsyncSession, user_id: int, kind: str, today: date) -> list[Task]:
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


async def _latest_briefing(session: AsyncSession, user_id: int, kind: str) -> Briefing | None:
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
            generated_at=datetime.now(UTC).replace(tzinfo=None),
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
    row = Briefing(user_id=user_id, kind=kind, content=content, tasks_fingerprint=fingerprint)
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
