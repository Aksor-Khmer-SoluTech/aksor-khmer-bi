import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { StatRowSkeleton } from "./Skeletons";
import type { Job, JobRun } from "../types";

function triggerSummary(job: Job): string {
  if (job.trigger_type === "cron") return job.cron_expression ?? "—";
  if (job.trigger_type === "interval") return `every ${job.interval_seconds}s`;
  return job.run_at ? new Date(job.run_at).toLocaleString() : "—";
}

function isToday(iso: string): boolean {
  const d = new Date(iso);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

interface RunRow {
  job: Job;
  run: JobRun;
}

/** A read-only "what's happening with jobs today" summary in the main
 * (non-admin) sidebar — Admin's Jobs page is for defining/editing job
 * schedules, this is for glancing at them, the way JasperReports Server
 * CE's own Scheduling view separates "manage schedules" from "what's
 * running." No backend aggregation endpoint exists for this yet, so it's
 * built from the same list/runs calls JobsPage already uses — fine at
 * this console's scale, worth revisiting if the job count grows large. */
export default function SchedulesPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.jobs
      .list()
      .then(async (jobList) => {
        if (cancelled) return;
        setJobs(jobList);
        const enabled = jobList.filter((j) => j.is_enabled);
        const perJob = await Promise.all(
          enabled.map((j) =>
            api.jobs
              .runs(j.id)
              .then((rs) => rs.map((run) => ({ job: j, run })))
              .catch(() => [] as RunRow[])
          )
        );
        if (cancelled) return;
        setRuns(perJob.flat());
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load jobs — is the API reachable?"));
    return () => {
      cancelled = true;
    };
  }, []);

  const todayRuns = useMemo(
    () =>
      (runs ?? [])
        .filter((r) => isToday(r.run.created_at))
        .sort((a, b) => b.run.created_at.localeCompare(a.run.created_at)),
    [runs]
  );

  const runningNow = todayRuns.filter((r) => r.run.status === "running" || r.run.status === "queued" || r.run.status === "retrying");
  const succeededToday = todayRuns.filter((r) => r.run.status === "success");
  const failedToday = todayRuns.filter((r) => r.run.status === "failed");

  // "Hasn't run today" is a floor, not a forecast — reading an exact next
  // fire time out of a cron expression would need a cron parser this app
  // doesn't have, so a weekly job that last ran yesterday shows up here
  // right alongside one that's genuinely due any minute.
  const ranTodayJobIds = useMemo(() => new Set(todayRuns.map((r) => r.job.id)), [todayRuns]);
  const notYetRunToday = (jobs ?? []).filter((j) => j.is_enabled && j.trigger_type !== "one_off" && !ranTodayJobIds.has(j.id));

  const loading = jobs === null && !error;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Schedules</h1>
          <p className="page-subtitle">What's running, what's finished, and what hasn't fired yet today.</p>
        </div>
      </div>

      {error && <p className="alert alert-error">{error}</p>}
      {loading && (
        <div className="panel">
          <StatRowSkeleton count={4} />
        </div>
      )}

      {jobs !== null && (
        <>
          <div className="panel">
            <div className="stat-row">
              <div>
                <div className="mono stat-number">{runningNow.length}</div>
                <div className="muted">running now</div>
              </div>
              <div>
                <div className="mono stat-number">{succeededToday.length}</div>
                <div className="muted">completed today</div>
              </div>
              <div>
                <div className="mono stat-number">{failedToday.length}</div>
                <div className="muted">failed today</div>
              </div>
              <div>
                <div className="mono stat-number">{notYetRunToday.length}</div>
                <div className="muted">haven't run today</div>
              </div>
            </div>
          </div>

          {todayRuns.length === 0 && notYetRunToday.length === 0 && jobs.length > 0 && (
            <div className="empty-state">
              <p>Nothing to show for today yet.</p>
            </div>
          )}

          {jobs.length === 0 && (
            <div className="empty-state">
              <p>No scheduled jobs yet.</p>
            </div>
          )}

          {todayRuns.length > 0 && (
            <div className="panel" style={{ marginTop: 20 }}>
              <span className="panel-title" style={{ fontSize: "1rem" }}>
                Today's runs
              </span>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {todayRuns.map((r) => (
                    <tr key={r.run.id}>
                      <td>{r.job.name}</td>
                      <td className="mono">{r.job.job_type}</td>
                      <td>
                        <span className={`badge badge-${r.run.status}`}>{r.run.status}</span>
                      </td>
                      <td className="muted">{new Date(r.run.started_at ?? r.run.created_at).toLocaleTimeString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {notYetRunToday.length > 0 && (
            <div className="panel" style={{ marginTop: 20 }}>
              <span className="panel-title" style={{ fontSize: "1rem" }}>
                Haven't run today
              </span>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Type</th>
                    <th>Trigger</th>
                  </tr>
                </thead>
                <tbody>
                  {notYetRunToday.map((j) => (
                    <tr key={j.id}>
                      <td>{j.name}</td>
                      <td className="mono">{j.job_type}</td>
                      <td className="mono">{triggerSummary(j)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
