from typing import Literal

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    name: str
    description: str | None = None
    job_type: Literal["render_report", "rest_call", "soap_call", "file_output", "data_alert"]
    config: dict = Field(..., description="Shape depends on job_type -- see app/job_executors.py's module docstring")
    trigger_type: Literal["cron", "interval", "one_off"]
    cron_expression: str | None = Field(None, examples=["*/15 * * * *"], description="trigger_type='cron' only")
    interval_seconds: int | None = Field(None, description="trigger_type='interval' only")
    run_at: str | None = Field(None, description="trigger_type='one_off' only, ISO 8601 UTC")
    start_date: str | None = Field(None, description="Job validity window start (cron/interval only), ISO 8601 UTC")
    end_date: str | None = Field(None, description="Job validity window end (cron/interval only), ISO 8601 UTC")
    is_enabled: bool = True
    max_retries: int = Field(0, ge=0)
    retry_backoff_seconds: int = Field(30, ge=0)


class JobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict | None = None
    trigger_type: Literal["cron", "interval", "one_off"] | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = None
    run_at: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0)
    retry_backoff_seconds: int | None = Field(None, ge=0)


class JobOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    job_type: str
    config: dict
    trigger_type: str
    cron_expression: str | None = None
    interval_seconds: int | None = None
    run_at: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_enabled: bool
    max_retries: int
    retry_backoff_seconds: int
    created_by: str | None = None
    created_at: str
    updated_at: str


class JobRunOut(BaseModel):
    id: str
    job_id: str
    triggered_by: str
    celery_task_id: str | None = None
    status: str
    attempt_number: int
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: str | None = None
    triggered_by_user_id: str | None = None
    created_at: str


class SchedulePreviewRequest(BaseModel):
    cron_expression: str
    start_date: str | None = Field(None, description="ISO 8601; as the job's own start_date")
    end_date: str | None = Field(None, description="ISO 8601; as the job's own end_date")
    count: int = Field(3, ge=1, le=10)


class SchedulePreview(BaseModel):
    timezone: str = Field(..., description="The time zone the scheduler reads the expression in")
    next_runs: list[str] = Field(..., description="ISO 8601 instants, earliest first; fewer than `count` when end_date comes first")


class JobDeliveryOut(BaseModel):
    """One file a run produced and where it went (db.JobDelivery) -- a line of the run history."""

    id: str
    run_id: str
    burst_value: str | None = None
    burst_label: str | None = Field(None, description="The value's name, e.g. Siem Reap for BR02")
    status: Literal["sent", "saved", "failed", "skipped"]
    reason: str | None = Field(None, description="Why it failed or was skipped; for a sent one, addresses the server refused")
    file_name: str | None = None
    size_bytes: int | None = None
    saved_to: str | None = None
    email_to: list[str] = Field(default_factory=list)
    email_cc: list[str] = Field(default_factory=list)
    subject: str | None = None
    sent_at: str | None = None
    attempts: int = 0
    can_resend: bool = Field(False, description="A failed email whose file is still kept")
