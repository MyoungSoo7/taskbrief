from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models import Task
from app.services import briefing_service


@pytest.fixture(autouse=True)
def _pin_kst(monkeypatch):
    """개발자 .env의 TIMEZONE 값과 무관하게 KST 기준으로 검증한다."""
    monkeypatch.setattr(
        briefing_service, "settings", SimpleNamespace(tzinfo=ZoneInfo("Asia/Seoul"))
    )


def _task(**kw) -> Task:
    defaults = dict(id=1, user_id=1, title="t", status="todo", priority="mid", due_date=None)
    defaults.update(kw)
    return Task(**defaults)


def test_fingerprint_is_order_insensitive():
    a = _task(id=1, title="a")
    b = _task(id=2, title="b")
    assert briefing_service._fingerprint([a, b]) == briefing_service._fingerprint([b, a])


def test_fingerprint_changes_when_status_changes():
    fp1 = briefing_service._fingerprint([_task(status="todo")])
    fp2 = briefing_service._fingerprint([_task(status="doing")])
    assert fp1 != fp2


def test_day_bounds_are_kst_midnight_in_utc():
    # KST 2026-07-06 00:00 == UTC 2026-07-05 15:00
    start, end = briefing_service._day_bounds(date(2026, 7, 6))
    assert start == datetime(2026, 7, 5, 15, 0)
    assert end == datetime(2026, 7, 6, 15, 0)


def test_week_bounds_start_monday():
    # 2026-07-06은 월요일
    start, end = briefing_service._week_bounds(date(2026, 7, 8))  # 수요일 기준
    assert start == datetime(2026, 7, 5, 15, 0)  # 월요일 KST 자정 == UTC 일요일 15시
    assert end == datetime(2026, 7, 12, 15, 0)


def test_urgent_count_counts_due_within_window():
    urgent_end = datetime(2026, 7, 9, 15, 0)  # today(7/6)+3일의 KST 자정 경계(UTC)
    tasks = [
        _task(id=1, due_date=datetime(2026, 7, 7, 3, 0)),  # 3일 이내 → urgent
        _task(id=2, due_date=datetime(2026, 7, 1, 0, 0)),  # 이미 지남 → urgent
        _task(id=3, due_date=datetime(2026, 7, 20, 0, 0)),  # 먼 미래 → not urgent
        _task(id=4, due_date=None, status="doing"),  # 마감 없음 → not urgent
    ]
    assert briefing_service._urgent_count(tasks, urgent_end) == 2
