from typing import Literal

from pydantic import BaseModel


class ReportRenderStats(BaseModel):
    """One row of GET /reports/analytics/summary -- render_count/
    error_count/avg_duration_ms are over the requested `days` window;
    last_rendered_at is unbounded (the most recent render ever, even if
    older than the window)."""

    report_id: str
    name: str
    render_count: int
    error_count: int
    avg_duration_ms: float | None = None
    p95_duration_ms: int | None = None
    last_rendered_at: str | None = None


class JobsSummary(BaseModel):
    """GET /jobs/summary -- org-wide totals plus today's execution
    counts. `running_now` is unbounded (a job still running from
    yesterday still counts), the rest are scoped to the calendar day in
    UTC."""

    total_jobs: int
    enabled_jobs: int
    runs_today: int
    succeeded_today: int
    failed_today: int
    running_now: int


class SecurityActivityItem(BaseModel):
    """One row of GET /security/activity -- a login_failed (from
    AuthEvent) or access_denied (from AccessDeniedEvent) event, merged
    into one chronological feed. `unusual` is computed at query time
    (>=3 login_failed for the same username within a trailing 15-minute
    window), not a stored classification -- see that route's docstring."""

    kind: Literal["login_failed", "access_denied"]
    username: str | None = None
    ip_address: str | None = None
    detail: str
    created_at: str
    unusual: bool = False


class MyRun(BaseModel):
    report_id: str
    name: str | None
    at: str
    via: str | None
    format: str | None
    parameters_selected: int | None
    ok: bool
    reason: str | None = None


class MyTopReport(BaseModel):
    report_id: str
    name: str | None
    runs: int


class MyDashboard(BaseModel):
    """The signed-in person's own activity -- nobody else's -- for the portal's Home page."""

    since: str
    runs_7d: int
    runs_30d: int
    failed_30d: int
    last_run_at: str | None
    recent: list[MyRun]
    top_reports: list[MyTopReport]
