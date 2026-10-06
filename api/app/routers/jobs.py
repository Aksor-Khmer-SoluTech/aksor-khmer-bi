"""Scheduled job CRUD, manual/API triggering, and run history --
app/scheduler.py picks up create/update/delete/enable/disable within one
poll interval (no separate signaling needed, see that module's
docstring); this router only ever touches the `jobs`/`job_runs` tables.

Auth: `job:manage` for create/update/delete, `job:view` for read routes,
`job:trigger` for `/run` -- the same permission a role or a direct grant
(app/rbac.py) can carry, so "trigger by API" (the plan's own wording) is
just "call this route with a credential that holds job:trigger," not a
separate webhook mechanism to maintain.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select

from .. import audit, db
from ..auth import ensure_org_scope, require_permission
from ..celery_app import celery_app
from ..models import JobCreate, JobOut, JobRunOut, JobsSummary, JobUpdate
from ..rbac import AuthContext

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_out(row: db.Job) -> JobOut:
    return JobOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        description=row.description,
        job_type=row.job_type,
        config=row.config,
        trigger_type=row.trigger_type,
        cron_expression=row.cron_expression,
        interval_seconds=row.interval_seconds,
        run_at=row.run_at,
        start_date=row.start_date,
        end_date=row.end_date,
        is_enabled=row.is_enabled,
        max_retries=row.max_retries,
        retry_backoff_seconds=row.retry_backoff_seconds,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _run_to_out(row: db.JobRun) -> JobRunOut:
    return JobRunOut(
        id=row.id,
        job_id=row.job_id,
        triggered_by=row.triggered_by,
        celery_task_id=row.celery_task_id,
        status=row.status,
        attempt_number=row.attempt_number,
        started_at=row.started_at,
        finished_at=row.finished_at,
        result_summary=row.result_summary,
        triggered_by_user_id=row.triggered_by_user_id,
        created_at=row.created_at,
    )


_AUDITED_FIELDS = (
    "name",
    "description",
    "config",
    "trigger_type",
    "cron_expression",
    "interval_seconds",
    "run_at",
    "start_date",
    "end_date",
    "is_enabled",
    "max_retries",
    "retry_backoff_seconds",
)


def _snapshot(row: db.Job) -> dict:
    return {f: getattr(row, f) for f in _AUDITED_FIELDS}


def _validate_trigger_fields(trigger_type: str, cron_expression, interval_seconds, run_at) -> None:
    if trigger_type == "cron":
        if not cron_expression:
            raise HTTPException(status_code=400, detail="trigger_type='cron' requires cron_expression")
        try:
            CronTrigger.from_crontab(cron_expression)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron_expression: {exc}") from exc
    elif trigger_type == "interval":
        if not interval_seconds or interval_seconds <= 0:
            raise HTTPException(status_code=400, detail="trigger_type='interval' requires a positive interval_seconds")
    elif trigger_type == "one_off":
        if not run_at:
            raise HTTPException(status_code=400, detail="trigger_type='one_off' requires run_at")
        try:
            datetime.fromisoformat(run_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid run_at: {exc}") from exc


@router.post("", summary="Create a scheduled job", response_model=JobOut)
def create_job(
    body: JobCreate,
    request: Request,
    org_id: str = Query(..., description="Organization this job belongs to"),
    context: AuthContext = Depends(require_permission("job:manage")),
) -> JobOut:
    ensure_org_scope(context, org_id)
    _validate_trigger_fields(body.trigger_type, body.cron_expression, body.interval_seconds, body.run_at)

    now = _now_iso()
    with db.SessionLocal() as session:
        if session.get(db.Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row = db.Job(
            org_id=org_id,
            name=body.name,
            description=body.description,
            job_type=body.job_type,
            config=body.config,
            trigger_type=body.trigger_type,
            cron_expression=body.cron_expression,
            interval_seconds=body.interval_seconds,
            run_at=body.run_at,
            start_date=body.start_date,
            end_date=body.end_date,
            is_enabled=body.is_enabled,
            max_retries=body.max_retries,
            retry_backoff_seconds=body.retry_backoff_seconds,
            created_by=context.user.id if context.user else None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "job.create", "job", row.id,
            label=row.name, org_id=org_id, summary=f'Created {row.trigger_type} job "{row.name}" ({row.job_type})',
            details={"job_type": row.job_type, "trigger_type": row.trigger_type, "is_enabled": row.is_enabled},
        )
        return _row_to_out(row)


@router.get("", summary="List jobs", response_model=list[JobOut])
def list_jobs(
    org_id: str | None = Query(None, description="Superusers may omit this to list every org's jobs"),
    context: AuthContext = Depends(require_permission("job:view")),
) -> list[JobOut]:
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    with db.SessionLocal() as session:
        query = select(db.Job).order_by(db.Job.name)
        if org_id is not None:
            query = query.where(db.Job.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_out(row) for row in rows]


@router.get("/summary", summary="Org-wide job totals and today's execution counts", response_model=JobsSummary)
def get_jobs_summary(
    org_id: str | None = Query(None, description="Superusers may omit this to see every org's jobs"),
    context: AuthContext = Depends(require_permission("job:view")),
) -> JobsSummary:
    """Backs the admin dashboard's job-totals panel
    (specs/admin_dashboard_design.md) -- replaces the client-side N+1
    (list() + per-job runs()) SchedulesPage.tsx currently does as an
    explicitly-flagged stopgap; that page migrating onto this endpoint
    is a natural follow-up, not required for this route to exist.
    Declared *before* GET /{job_id} below so "/jobs/summary" doesn't get
    swallowed by that path-parameter route (Starlette matches in
    declaration order).
    """
    if org_id is not None:
        ensure_org_scope(context, org_id)
    elif not context.is_superuser:
        org_id = context.org_id

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db.SessionLocal() as session:
        jobs_query = select(db.Job)
        if org_id is not None:
            jobs_query = jobs_query.where(db.Job.org_id == org_id)
        jobs = session.execute(jobs_query).scalars().all()
        job_ids = [j.id for j in jobs]

        runs_today: list[db.JobRun] = []
        running_now = 0
        if job_ids:
            runs_today = (
                session.execute(
                    select(db.JobRun).where(db.JobRun.job_id.in_(job_ids), db.JobRun.created_at >= today_start)
                )
                .scalars()
                .all()
            )
            running_now = session.execute(
                select(func.count(db.JobRun.id)).where(
                    db.JobRun.job_id.in_(job_ids), db.JobRun.status.in_(("running", "queued", "retrying"))
                )
            ).scalar_one()

        return JobsSummary(
            total_jobs=len(jobs),
            enabled_jobs=sum(1 for j in jobs if j.is_enabled),
            runs_today=len(runs_today),
            succeeded_today=sum(1 for r in runs_today if r.status == "success"),
            failed_today=sum(1 for r in runs_today if r.status == "failed"),
            running_now=running_now,
        )


@router.get("/{job_id}", summary="Get one job", response_model=JobOut)
def get_job(job_id: str, context: AuthContext = Depends(require_permission("job:view"))) -> JobOut:
    with db.SessionLocal() as session:
        row = session.get(db.Job, job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_org_scope(context, row.org_id)
        return _row_to_out(row)


@router.patch("/{job_id}", summary="Update a job", response_model=JobOut)
def update_job(
    job_id: str, body: JobUpdate, request: Request, context: AuthContext = Depends(require_permission("job:manage"))
) -> JobOut:
    with db.SessionLocal() as session:
        row = session.get(db.Job, job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_org_scope(context, row.org_id)

        # Deep-copied: `config` is a JSON dict the ORM hands back by reference.
        before = copy.deepcopy(_snapshot(row))
        for field in _AUDITED_FIELDS:
            value = getattr(body, field)
            if value is not None:
                setattr(row, field, value)

        _validate_trigger_fields(row.trigger_type, row.cron_expression, row.interval_seconds, row.run_at)
        row.updated_at = _now_iso()
        session.commit()
        changes = audit.diff(before, _snapshot(row), list(_AUDITED_FIELDS))
        if changes:
            enabled = next((c for c in changes if c["field"] == "is_enabled"), None)
            audit.record(
                audit.Actor.of(context, request), "job.update", "job", row.id,
                label=row.name, org_id=row.org_id,
                summary=(f'{"Enabled" if enabled["after"] else "Disabled"} job "{row.name}"' if enabled and len(changes) == 1
                         else f'Updated job "{row.name}" (' + ", ".join(c["field"] for c in changes) + ")"),
                changes=changes,
            )
        return _row_to_out(row)


@router.delete("/{job_id}", status_code=204, summary="Delete a job")
def delete_job(job_id: str, request: Request, context: AuthContext = Depends(require_permission("job:manage"))) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.Job, job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_org_scope(context, row.org_id)
        session.delete(row)
        session.commit()
        audit.record(
            audit.Actor.of(context, request), "job.delete", "job", job_id,
            label=row.name, org_id=row.org_id, summary=f'Deleted job "{row.name}"',
            details={"job_type": row.job_type, "trigger_type": row.trigger_type},
        )


@router.post(
    "/{job_id}/run",
    summary="Trigger a job immediately (a person clicking 'run now', or an external system invoking it via the API)",
    response_model=JobRunOut,
)
def run_job_now(job_id: str, context: AuthContext = Depends(require_permission("job:trigger"))) -> JobRunOut:
    # There's no reliable way to tell "a person clicked a button in the
    # portal" apart from "a script called this same authenticated route"
    # from the request alone -- both look identical server-side. Recorded
    # as "manual" either way; "api" is reserved in the schema for a future
    # distinct non-interactive auth mechanism (an API key, say) that would
    # actually be distinguishable, rather than guessed at here.
    with db.SessionLocal() as session:
        job = session.get(db.Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_org_scope(context, job.org_id)

        run = db.JobRun(
            job_id=job.id,
            triggered_by="manual",
            status="queued",
            attempt_number=1,
            triggered_by_user_id=context.user.id if context.user else None,
            created_at=_now_iso(),
        )
        session.add(run)
        session.commit()
        run_out = _run_to_out(run)

    celery_app.send_task("run_job", args=[job_id, run_out.id])
    return run_out


@router.get("/{job_id}/runs", summary="Job run history", response_model=list[JobRunOut])
def list_job_runs(
    job_id: str,
    status: str | None = Query(None, description="Filter by status: queued|running|success|failed|retrying"),
    context: AuthContext = Depends(require_permission("job:view")),
) -> list[JobRunOut]:
    with db.SessionLocal() as session:
        job = session.get(db.Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_org_scope(context, job.org_id)

        query = select(db.JobRun).where(db.JobRun.job_id == job_id).order_by(db.JobRun.created_at.desc())
        if status is not None:
            query = query.where(db.JobRun.status == status)
        rows = session.execute(query).scalars().all()
        return [_run_to_out(row) for row in rows]
