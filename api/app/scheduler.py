"""The *when* half of the scheduler/worker split (app/celery_app.py is
the *how* half). Runs as its own single-replica process (`scheduler`
service, docker-compose.yml) -- single-replica specifically so a cron
trigger never fires twice, which is why this process does not execute
job logic itself: on fire, it only enqueues a Celery task and returns,
so the actual work happens in the horizontally-scalable `worker`
service instead.

APScheduler + `SQLAlchemyJobStore` (same Postgres `DATABASE_URL` as
everything else) is the direct Python analog to Quartz's JobStore +
CronTrigger -- durable across restarts, the same durability guarantee
Quartz gives. It keeps its own bookkeeping table (`apscheduler_jobs`,
created automatically) entirely separate from this project's own `jobs`
table (app/db.py's `Job`, the user-facing definition); this module is
what bridges the two.

Dynamic updates (create/edit/pause/delete a job via the API) are picked
up by *polling* `jobs` on a short interval (`_RECONCILE_INTERVAL_SECONDS`)
rather than a second signaling protocol between `api` and `scheduler` --
simpler, and adequate at this scale (a job's cron edit takes up to one
poll interval to take effect, not sub-second). Each poll:
  - (re-)registers an APScheduler trigger for every enabled `Job` row,
    keyed by the job's own id (`replace_existing=True`, so re-adding an
    unchanged job is a cheap no-op and a changed one is transparently
    rescheduled);
  - removes any APScheduler-registered job whose id is no longer in that
    enabled set (disabled or deleted since the last poll).

Run with:
    python -m app.scheduler
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from . import db
from .celery_app import celery_app
from .db import Job, JobRun
from .logging_config import configure_logging

_log = logging.getLogger("aksor_khmer_bi.scheduler")

_RECONCILE_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_RECONCILE_INTERVAL_SECONDS", "15"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None):
    return datetime.fromisoformat(value) if value else None


def _build_trigger(job: Job):
    if job.trigger_type == "cron":
        return CronTrigger.from_crontab(
            job.cron_expression, start_date=_parse_iso(job.start_date), end_date=_parse_iso(job.end_date)
        )
    if job.trigger_type == "interval":
        return IntervalTrigger(
            seconds=job.interval_seconds, start_date=_parse_iso(job.start_date), end_date=_parse_iso(job.end_date)
        )
    if job.trigger_type == "one_off":
        return DateTrigger(run_date=_parse_iso(job.run_at))
    raise ValueError(f"Unknown trigger_type: {job.trigger_type!r}")


def fire_job(job_id: str) -> None:
    """The function APScheduler actually calls when a trigger fires.
    Creates the JobRun row and enqueues the Celery task -- does not run
    the job itself (see module docstring). One-off jobs disable
    themselves after firing so the next reconcile pass stops re-adding
    them (APScheduler already drops a spent DateTrigger from its own
    store; this keeps *our* `jobs` table's `is_enabled` consistent with
    that instead of silently diverging from it).
    """
    with db.SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None or not job.is_enabled:
            _log.info("fire_job: job_id=%r no longer exists/enabled, skipping", job_id)
            return

        run = JobRun(
            job_id=job.id,
            triggered_by="schedule",
            status="queued",
            attempt_number=1,
            created_at=_now_iso(),
        )
        session.add(run)
        session.flush()
        run_id = run.id

        if job.trigger_type == "one_off":
            job.is_enabled = False

        session.commit()

    _log.info("Enqueuing job_id=%r run_id=%r", job_id, run_id)
    celery_app.send_task("run_job", args=[job_id, run_id])


# job_id -> a fingerprint of its trigger-relevant fields, as of the last
# time this process actually (re)registered it with APScheduler. Process-
# local and reset on restart is fine -- a restart re-registers everything
# fresh anyway (see reconcile()'s "not yet registered" branch below).
#
# Necessary, not just an optimization: `add_job(..., replace_existing=True)`
# always recomputes next_run_time from "now", even for a trigger that's
# identical to what's already registered. Calling it unconditionally on
# every reconcile pass -- confirmed the hard way, by actually watching a
# job with a 10s interval never fire once while being reconciled every 5s
# -- perpetually pushes an unchanged job's next fire time forward before
# it's ever reached. Only touching APScheduler when something *actually*
# changed (or the job isn't registered yet at all) is what makes a
# steady-state interval/cron job actually fire on its own.
_registered_fingerprints: dict[str, str] = {}


def _trigger_fingerprint(job: Job) -> str:
    return "|".join(
        str(x) for x in (job.trigger_type, job.cron_expression, job.interval_seconds, job.run_at, job.start_date, job.end_date)
    )


def reconcile(scheduler: BlockingScheduler) -> None:
    with db.SessionLocal() as session:
        enabled_jobs = session.execute(select(Job).where(Job.is_enabled.is_(True))).scalars().all()

    enabled_ids = set()
    for job in enabled_jobs:
        enabled_ids.add(job.id)
        fingerprint = _trigger_fingerprint(job)
        if _registered_fingerprints.get(job.id) == fingerprint and scheduler.get_job(job.id) is not None:
            continue  # unchanged and already live -- leave its next_run_time alone

        try:
            trigger = _build_trigger(job)
        except (ValueError, KeyError) as exc:
            _log.error("Skipping malformed job_id=%r: %s", job.id, exc)
            continue
        scheduler.add_job(fire_job, trigger=trigger, id=job.id, args=[job.id], replace_existing=True, misfire_grace_time=60)
        _registered_fingerprints[job.id] = fingerprint
        _log.info("(Re)registered job_id=%r (%s)", job.id, job.trigger_type)

    for existing in scheduler.get_jobs():
        if existing.id not in enabled_ids:
            scheduler.remove_job(existing.id)
            _registered_fingerprints.pop(existing.id, None)
            _log.info("Removed job_id=%r from the live scheduler (disabled or deleted)", existing.id)


def _reconcile_loop(scheduler: BlockingScheduler) -> None:
    """Runs in a plain background thread, *not* as an APScheduler job --
    `SQLAlchemyJobStore` pickles every job it's given (to survive a
    restart), and a live `BlockingScheduler` instance is deliberately not
    picklable (APScheduler raises `TypeError` rather than let you shoot
    yourself in the foot this way, discovered by actually running this,
    not anticipated up front). A plain thread sidesteps the problem
    entirely: it isn't a job APScheduler ever needs to persist.
    """
    while True:
        time.sleep(_RECONCILE_INTERVAL_SECONDS)
        try:
            reconcile(scheduler)
        except Exception:
            _log.exception("Reconcile pass failed")


def main() -> None:
    configure_logging(service="scheduler")
    scheduler = BlockingScheduler(jobstores={"default": SQLAlchemyJobStore(url=db.DATABASE_URL)})

    reconcile(scheduler)
    threading.Thread(target=_reconcile_loop, args=(scheduler,), daemon=True).start()

    _log.info("Scheduler starting (reconciling every %ss)", _RECONCILE_INTERVAL_SECONDS)
    scheduler.start()


if __name__ == "__main__":
    main()
