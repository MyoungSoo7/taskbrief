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
