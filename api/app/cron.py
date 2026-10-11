"""A job's cron schedule as an APScheduler trigger -- the one place it is built, so the scheduler that fires it, the
router that validates it and the portal's "next runs" preview always read an expression the same way.

Two things APScheduler 3's own `CronTrigger.from_crontab` gets wrong for a crontab expression:

- **Weekday numbers.** Crontab counts 0 (and 7) as Sunday; APScheduler 3 counts 0 as Monday (a known historical
  mismatch, kept for compatibility -- see its docstring). Taken as-is, "1-5" would fire Tuesday to Saturday. Here
  numbers are turned into day names (`mon,tue,...`), which mean the same to both.
- **Validity window.** `from_crontab` takes no start/end date; the job's `start_date`/`end_date` are passed to the
  trigger itself.

The time zone is REPORT_TIMEZONE (UTC when unset): "08:00" is 08:00 there, the same zone a `now()` filter default
reads "today" in when the job runs (report_data._report_timezone).
"""
from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

from .report_data import _report_timezone

_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _day(token: str) -> int:
    if not token.isdigit() or int(token) > 7:
        raise ValueError(f"{token!r} isn't a day of the week (0-7, where 0 and 7 are Sunday, or sun-sat)")
    return int(token) % 7


def crontab_weekdays(field: str) -> str:
    """A crontab day-of-week field in APScheduler's terms: each numeric part becomes the day names it covers; names
    and `*` pass through unchanged."""
    parts = []
    for part in field.split(","):
        base, _, step = part.partition("/")
        if not any(ch.isdigit() for ch in base):
            if base == "*" and step:  # */2 -- every other day *from Sunday*, in crontab's numbering
                parts.extend(_DAY_NAMES[d] for d in range(0, 7, int(step)))
            else:
                parts.append(part)
            continue
        start, _, end = base.partition("-")
        first = int(start) if start.isdigit() else -1
        last = int(end) if end else (6 if step else first)
        if first < 0 or not (end == "" or end.isdigit()) or last > 7:
            raise ValueError(f"{part!r} isn't a day of the week (0-7, where 0 and 7 are Sunday, or sun-sat)")
        days = range(first, last + 1, int(step) if step else 1)
        if not days:
            raise ValueError(f"{part!r} runs backwards -- write a wrapping range as two, e.g. 5-6,0")
        parts.extend(_DAY_NAMES[_day(str(d))] for d in days)
    # A day named twice (0 and 7 are both Sunday) is harmless to APScheduler, but keep the list tidy.
    return ",".join(dict.fromkeys(parts))


def cron_trigger(expression: str, start_date: str | None = None, end_date: str | None = None) -> CronTrigger:
    """Raises ValueError (with a readable message) for an expression that isn't five valid crontab fields."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"A schedule has 5 fields (minute hour day month weekday); this has {len(fields)}")
    minute, hour, day, month, weekday = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=crontab_weekdays(weekday),
        start_date=datetime.fromisoformat(start_date) if start_date else None,
        end_date=datetime.fromisoformat(end_date) if end_date else None,
        timezone=_report_timezone(),
    )
