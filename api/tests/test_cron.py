"""A job's cron expression read the crontab way (app/cron.py): Sunday is 0, the validity window applies, and the
scheduler builds every cron job without falling over."""
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app import scheduler as app_scheduler
from app.cron import cron_trigger, crontab_weekdays
from app.db import Job


def _next(expression: str, after: datetime, count: int = 7, **window) -> list[datetime]:
    trigger = cron_trigger(expression, **window)
    runs, previous, now = [], None, after
    while len(runs) < count:
        fire = trigger.get_next_fire_time(previous, now)
        if fire is None:
            break
        runs.append(fire)
        previous = now = fire
    return runs


MONDAY = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)  # a Monday


@pytest.mark.parametrize(
    "field, expected",
    [
        ("1-5", "mon,tue,wed,thu,fri"),
        ("0", "sun"),
        ("7", "sun"),
        ("0,6", "sun,sat"),
        ("5-7", "fri,sat,sun"),
        ("*/2", "sun,tue,thu,sat"),
        ("1-5/2", "mon,wed,fri"),
        ("*", "*"),
        ("mon-fri", "mon-fri"),
    ],
)
def test_crontab_weekday_numbers_become_day_names(field, expected):
    assert crontab_weekdays(field) == expected


@pytest.mark.parametrize("field", ["8", "6-1", "x-2", "1-9"])
def test_impossible_weekdays_are_refused(field):
    with pytest.raises(ValueError):
        crontab_weekdays(field)


def test_weekdays_means_monday_to_friday_not_tuesday_to_saturday(monkeypatch):
    monkeypatch.delenv("REPORT_TIMEZONE", raising=False)
    runs = _next("30 8 * * 1-5", MONDAY, count=10)
    assert {r.strftime("%a") for r in runs} == {"Mon", "Tue", "Wed", "Thu", "Fri"}
    assert all((r.hour, r.minute) == (8, 30) for r in runs)
    assert _next("0 9 * * 0", MONDAY, count=1)[0].strftime("%a %d") == "Sun 18"


def test_the_schedule_is_read_in_report_timezone(monkeypatch):
    monkeypatch.setenv("REPORT_TIMEZONE", "Asia/Phnom_Penh")
    first = _next("0 8 * * *", MONDAY, count=1)[0]
    assert (first.hour, str(first.tzinfo)) == (8, "Asia/Phnom_Penh")
    assert first.astimezone(timezone.utc).hour == 1  # 08:00 in Phnom Penh is 01:00 UTC


def test_the_validity_window_applies():
    start = (MONDAY + timedelta(days=2)).isoformat()
    end = (MONDAY + timedelta(days=3, hours=12)).isoformat()
    runs = _next("0 8 * * *", MONDAY, start_date=start, end_date=end)
    assert [r.day for r in runs] == [14, 15]


@pytest.mark.parametrize("expression", ["every day", "0 8 * *", "61 8 * * *", "0 8 * * 9"])
def test_a_bad_expression_is_a_value_error(expression):
    with pytest.raises(ValueError):
        cron_trigger(expression)


def test_the_scheduler_registers_a_cron_job_and_a_broken_one_doesnt_stop_the_rest(monkeypatch):
    jobs = [
        Job(id="cron1", trigger_type="cron", cron_expression="0 8 * * 1-5", start_date="2026-01-01T00:00:00+00:00", end_date=None,
            interval_seconds=None, run_at=None, is_enabled=True),
        Job(id="bad1", trigger_type="cron", cron_expression="0 8 * * 9", start_date=None, end_date=None,
            interval_seconds=None, run_at=None, is_enabled=True),
        Job(id="every1", trigger_type="interval", cron_expression=None, start_date=None, end_date=None,
            interval_seconds=60, run_at=None, is_enabled=True),
    ]

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, _query):
            return _Result(jobs)

    monkeypatch.setattr(app_scheduler.db, "SessionLocal", _Session)
    monkeypatch.setattr(app_scheduler, "_registered_fingerprints", {})
    sched = BackgroundScheduler()
    sched.start(paused=True)
    try:
        app_scheduler.reconcile(sched)
        assert sorted(j.id for j in sched.get_jobs()) == ["cron1", "every1"]
    finally:
        sched.shutdown(wait=False)
