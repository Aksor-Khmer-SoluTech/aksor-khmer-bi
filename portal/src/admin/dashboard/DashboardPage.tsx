import { useEffect, useState } from "react";
import { api, ApiError } from "../../api";
import type { AuthInfo, JobsSummary, ReportRenderStats, SecurityActivityItem } from "../../types";
import { AccessDeniedIcon, AuthFailureIcon } from "../icons";
import { MetricMeter } from "../monitor/MetricMeter";
import { has } from "../sections";
import AuditFeed from "../../components/AuditFeed";
import { LinesSkeleton, StatRowSkeleton, TableSkeleton } from "../../components/Skeletons";

/** Admin's landing page (see sections.tsx -- first in ADMIN_SECTIONS):
 * report usage, job execution, and security activity, each panel gated
 * on its own permission rather than the whole page behind one. See
 * specs/admin_dashboard_design.md -- this reads three new endpoints
 * (GET /reports/analytics/summary, GET /jobs/summary, GET
 * /security/activity), each backed by real instrumentation added
 * alongside this page, not pre-existing data. */
export default function DashboardPage({ auth }: { auth: AuthInfo }) {
  const canViewReports = has(auth, "report:view");
  const canViewJobs = has(auth, "job:view");
  const canViewAudit = has(auth, "audit:view");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Report usage, scheduled-job execution, security activity, and recent changes.</p>
        </div>
      </div>

      <div className="stack" style={{ gap: 20 }}>
        {canViewReports && <RenderStatsPanel />}
        {canViewJobs && <JobsSummaryPanel />}
        {canViewAudit && <SecurityActivityPanel />}
        {canViewAudit && <RecentChangesPanel />}
        {!canViewReports && !canViewJobs && !canViewAudit && (
          <p className="muted">Nothing to show yet -- ask an administrator for report:view, job:view, or audit:view.</p>
        )}
      </div>
    </div>
  );
}

function RenderStatsPanel() {
  const [rows, setRows] = useState<ReportRenderStats[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.analytics
      .renderStats({ days: 30, limit: 10 })
      .then(setRows)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load render statistics"));
  }, []);

  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 4 }}>
        <span className="panel-title" style={{ fontSize: "1rem" }}>
          Popular templates
        </span>
        <span className="muted mono" style={{ fontSize: "0.78rem" }}>
          last 30 days
        </span>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {!rows && !error && <TableSkeleton columns={["Report", "Renders", "Avg time", "p95", "Errors"]} rows={5} />}
      {rows && rows.length === 0 && <p className="muted">No renders recorded in this window yet.</p>}

      {rows && rows.length > 0 && (
        <table className="data-table" style={{ cursor: "default" }}>
          <thead>
            <tr>
              <th>Report</th>
              <th>Renders</th>
              <th>Avg time</th>
              <th>p95</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.report_id} style={{ cursor: "default" }}>
                <td>{r.name}</td>
                <td className="mono">{r.render_count}</td>
                <td className="mono">{r.avg_duration_ms != null ? `${Math.round(r.avg_duration_ms)} ms` : "—"}</td>
                <td className="mono">{r.p95_duration_ms != null ? `${r.p95_duration_ms} ms` : "—"}</td>
                <td className="mono">{r.error_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function JobsSummaryPanel() {
  const [summary, setSummary] = useState<JobsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.jobs
      .summary()
      .then(setSummary)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load job totals"));
  }, []);

  return (
    <div className="panel">
      <span className="panel-title" style={{ fontSize: "1rem" }}>
        Scheduled jobs
      </span>

      {error && <p className="alert alert-error">{error}</p>}
      {!summary && !error && <StatRowSkeleton count={6} />}

      {summary && (
        <>
          <div className="stat-row">
            <div>
              <div className="mono stat-number">{summary.total_jobs}</div>
              <div className="muted">total jobs</div>
            </div>
            <div>
              <div className="mono stat-number">{summary.enabled_jobs}</div>
              <div className="muted">enabled</div>
            </div>
            <div>
              <div className="mono stat-number">{summary.running_now}</div>
              <div className="muted">running now</div>
            </div>
            <div>
              <div className="mono stat-number">{summary.runs_today}</div>
              <div className="muted">runs today</div>
            </div>
            <div>
              <div className="mono stat-number">{summary.succeeded_today}</div>
              <div className="muted">succeeded today</div>
            </div>
            <div>
              <div className="mono stat-number">{summary.failed_today}</div>
              <div className="muted">failed today</div>
            </div>
          </div>
          {summary.runs_today > 0 && (
            <MetricMeter
              label="Today's failure rate"
              percent={(summary.failed_today / summary.runs_today) * 100}
              sublabel={`${summary.failed_today} of ${summary.runs_today} runs`}
            />
          )}
        </>
      )}
    </div>
  );
}

/** The third question an investigation asks, after "who signed in" and "who
 * was refused" (SecurityActivityPanel above): "what was changed?" -- the
 * latest few entries of the change audit trail, with the full searchable
 * log one click away. */
function RecentChangesPanel() {
  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 10 }}>
        <span className="panel-title" style={{ fontSize: "1rem" }}>
          Recent changes
        </span>
        <a className="link-btn" href="#/admin/audit">
          Open the audit log →
        </a>
      </div>
      <AuditFeed query={{}} limit={8} emptyText="No changes recorded yet." />
    </div>
  );
}

function SecurityActivityPanel() {
  const [items, setItems] = useState<SecurityActivityItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.security
      .activity({ sinceHours: 24, limit: 50 })
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load security activity"));
  }, []);

  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 4 }}>
        <span className="panel-title" style={{ fontSize: "1rem" }}>
          Recent security activity
        </span>
        <span className="muted mono" style={{ fontSize: "0.78rem" }}>
          last 24 hours
        </span>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {!items && !error && <LinesSkeleton count={4} />}
      {items && items.length === 0 && <p className="muted">Nothing recorded in this window.</p>}

      {items && items.length > 0 && (
        <div className="stack">
          {items.map((item, i) => (
            <div
              key={i}
              className={`flex items-start gap-3 rounded-sm border px-3 py-2.5 ${
                item.unusual ? "border-danger-strong bg-danger-soft" : "border-border-soft"
              }`}
            >
              <span className={`mt-0.5 ${item.kind === "login_failed" ? "text-danger" : "text-highlight"}`}>
                {item.kind === "login_failed" ? <AuthFailureIcon /> : <AccessDeniedIcon />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[0.88rem] font-medium text-text">
                  {item.username ?? "unknown user"} · {item.detail}
                  {item.unusual && <span className="ml-2 text-[0.72rem] font-semibold text-danger-strong">UNUSUAL</span>}
                </div>
                <div className="mt-0.5 text-[0.78rem] text-text-faint">
                  <span className="mono">{item.ip_address ?? "unknown IP"}</span> · {new Date(item.created_at).toLocaleString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
