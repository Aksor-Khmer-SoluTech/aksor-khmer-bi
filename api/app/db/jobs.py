"""Quartz-style job scheduling (Phase 3) -- see app/scheduler.py (decides
*when*, APScheduler + this same Postgres as its jobstore) and
app/celery_app.py + app/job_executors.py (decide *how*, Celery/Redis,
with per-job retry). `Job` is the user-facing definition; APScheduler
keeps its own separate bookkeeping table (`apscheduler_jobs`, created by
its SQLAlchemyJobStore, not defined here) for trigger/fire-time state --
the scheduler process is what bridges the two, not this schema.
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _gen_id


class Job(Base):
    """One scheduled (or one-off, or purely manual/API-triggered) job
    definition. `config`'s shape depends on `job_type` -- see
    app/job_executors.py's module docstring for each type's exact keys.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)  # "render_report"|"rest_call"|"soap_call"|"file_output"
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)  # "cron"|"interval"|"one_off"
    cron_expression: Mapped[str | None] = mapped_column(String, nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_at: Mapped[str | None] = mapped_column(String, nullable=True)  # one_off only, ISO 8601
    # The job's own validity window -- independent of (but complementary
    # to) any Phase-1 access-grant expiry. A cron trigger outside this
    # window simply doesn't fire; it's not deleted or disabled.
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # The APScheduler-side job id this definition is registered under --
    # always equal to this row's own `id` in practice (app/scheduler.py
    # registers with id=job.id), kept as an explicit column rather than
    # assumed so a future re-keying scheme wouldn't be a silent breakage.
    apscheduler_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class JobRun(Base):
    """One firing's history -- the audit trail Jasper's own Job Scheduler
    shows as its "job log." `status` transitions
    queued -> running -> (success | failed | retrying -> running -> ...).
    """

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)  # "schedule"|"manual"|"api"
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class JobDelivery(Base):
    """One file a run produced and where it went -- a line of the job's run history. A run of a job split by a
    filter (bursting: one file per branch, say) has one per value; an unsplit run has one. `status`:
    "sent" (emailed), "saved" (written to the folder, no email), "failed" (`reason` says why), or "skipped" (no
    data for that value, or nobody to send it to). The file itself is kept for a while (`file_path`, under
    data/job_outputs) so a failed email can be re-sent with the very same report."""

    __tablename__ = "job_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    burst_value: Mapped[str | None] = mapped_column(String, nullable=True)
    burst_label: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_to: Mapped[str | None] = mapped_column(String, nullable=True)
    email_to: Mapped[list | None] = mapped_column(JSON, nullable=True)
    email_cc: Mapped[list | None] = mapped_column(JSON, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
