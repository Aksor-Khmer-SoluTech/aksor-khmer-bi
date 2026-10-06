"""Celery application + the one task (`run_job`) every job firing goes
through, regardless of job_type. This is the *execution* half of the
scheduler/worker split (see app/scheduler.py's module docstring for the
other half): app/scheduler.py's APScheduler decides *when* to fire a job
and enqueues this task; a separate `celery -A app.celery_app worker`
process (`worker` service, docker-compose.yml) picks it up and actually
runs it, with per-job retry/backoff -- explicitly requested over a
simpler in-process call specifically for that retry mechanism.

Run a worker with:
    celery -A app.celery_app worker --loglevel=info

`REDIS_URL` selects the broker and result backend (same database number
for both, different key prefixes internally -- Celery handles that).
Unset falls back to `redis://localhost:6379/0`, for local dev against a
plain `docker run redis` with no other configuration.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from celery import Celery

from . import db
from .db import Job, JobRun
from .job_executors import PermanentJobError, RetryableJobError, execute

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_log = logging.getLogger("aksor_khmer_bi.celery")

celery_app = Celery("aksor_khmer_bi", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # A job's own retry_backoff_seconds is applied manually (see below)
    # rather than Celery's built-in exponential backoff, since it's a
    # per-job value read from the database, not a fixed per-task-type
    # policy Celery's decorator-level options can express.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@celery_app.task(bind=True, name="run_job")
def run_job(self, job_id: str, run_id: str) -> str:
    """Load `job_id`/`run_id`, execute via app/job_executors.execute,
    update the JobRun row at each transition. Retries (with the job's
    own max_retries/retry_backoff_seconds) only for RetryableJobError;
    anything else fails the run immediately, no retry.
    """
    with db.SessionLocal() as session:
        job = session.get(Job, job_id)
        run = session.get(JobRun, run_id)
        if job is None or run is None:
            _log.error("run_job: job_id=%r or run_id=%r not found, dropping", job_id, run_id)
            return "job or run not found"

        run.status = "running"
        run.started_at = run.started_at or _now_iso()
        run.attempt_number = self.request.retries + 1
        run.celery_task_id = self.request.id
        session.commit()

        try:
            result_summary = execute(job)
        except RetryableJobError as exc:
            if self.request.retries < job.max_retries:
                run.status = "retrying"
                run.result_summary = str(exc)[:2000]
                session.commit()
                raise self.retry(exc=exc, countdown=job.retry_backoff_seconds, max_retries=job.max_retries)
            run.status = "failed"
            run.result_summary = f"Exhausted {job.max_retries} retries: {exc}"[:2000]
            run.finished_at = _now_iso()
            session.commit()
            raise
        except PermanentJobError as exc:
            run.status = "failed"
            run.result_summary = str(exc)[:2000]
            run.finished_at = _now_iso()
            session.commit()
            raise
        except Exception as exc:  # pragma: no cover -- executors are expected to classify their own failures
            run.status = "failed"
            run.result_summary = f"Unclassified error: {exc}"[:2000]
            run.finished_at = _now_iso()
            session.commit()
            raise

        run.status = "success"
        run.result_summary = result_summary[:2000] if result_summary else None
        run.finished_at = _now_iso()
        session.commit()
        return result_summary
