from typing import Literal

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    name: str
    description: str | None = None
    job_type: Literal["render_report", "rest_call", "soap_call", "file_output"]
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
