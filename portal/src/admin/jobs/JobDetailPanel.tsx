import { Fragment, useEffect, useState, type FormEvent } from "react";
import { ChevronDown, ChevronUp, RotateCw } from "lucide-react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { Job, JobDelivery, JobRun } from "../../types";
import JobFields, { draftFromJob, draftToBody, type JobDraft } from "./JobFields";

type Tab = "settings" | "runs";

export default function JobDetailPanel({
  job,
  onUpdated,
  onDeleted,
}: {
  job: Job;
  onUpdated: (j: Job) => void;
  onDeleted: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("settings");

  const [name, setName] = useState(job.name);
  const [description, setDescription] = useState(job.description ?? "");
  const [isEnabled, setIsEnabled] = useState(job.is_enabled);
  const [draft, setDraft] = useState<JobDraft>(() => draftFromJob(job));
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [runs, setRuns] = useState<JobRun[] | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  function loadRuns() {
    api.jobs.runs(job.id).then(setRuns).catch(() => setRunsError("Couldn't load run history"));
  }

  useEffect(() => {
    if (tab === "runs") loadRuns();
    // loadRuns is re-created each render but only depends on job.id
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, job.id]);

  async function saveSettings(e: FormEvent) {
    e.preventDefault();
    setSettingsError(null);
    setSettingsSaved(false);

    const body = draftToBody(draft);
    if ("error" in body) {
      setSettingsError(body.error);
      return;
    }

    setSavingSettings(true);
    try {
      const updated = await api.jobs.update(job.id, {
        name,
        description: description || null,
        is_enabled: isEnabled,
        ...body,
      });
      onUpdated(updated);
      setSettingsSaved(true);
    } catch (err) {
      setSettingsError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSavingSettings(false);
    }
  }

  async function confirmDelete() {
    try {
      await api.jobs.delete(job.id);
      onDeleted(job.id);
    } catch (err) {
      setSettingsError(err instanceof ApiError ? err.message : "Couldn't delete");
    } finally {
      setDeleteOpen(false);
    }
  }

  async function runNow() {
    setRunning(true);
    setRunsError(null);
    try {
      await api.jobs.run(job.id);
      loadRuns();
    } catch (err) {
      setRunsError(err instanceof ApiError ? err.message : "Couldn't trigger the job");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="admin-detail" onClick={(e) => e.stopPropagation()}>
      <div className="tabs">
        <button type="button" className={`tab ${tab === "settings" ? "active" : ""}`} onClick={() => setTab("settings")}>
          Settings
        </button>
        <button type="button" className={`tab ${tab === "runs" ? "active" : ""}`} onClick={() => setTab("runs")}>
          Run history
        </button>
      </div>

      {tab === "settings" && (
        <form onSubmit={saveSettings} className="stack">
          <div className="row">
            <label>
              <span>Name</span>
              <input type="text" required value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              <span>Description</span>
              <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
          </div>

          <JobFields draft={draft} onChange={setDraft} canChangeType={false} />

          <label className="checkbox-label">
            <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} /> Enabled
          </label>

          {settingsError && <p className="alert alert-error">{settingsError}</p>}
          {settingsSaved && <p className="alert alert-success">Saved.</p>}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setDeleteOpen(true)}>
              Delete job
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={savingSettings}>
              {savingSettings && <span className="spinner" />}
              Save
            </button>
          </div>
        </form>
      )}

      {tab === "runs" && (
        <div className="stack">
          <div>
            <button type="button" className="btn btn-primary btn-sm" onClick={runNow} disabled={running}>
              {running && <span className="spinner" />}
              Run now
            </button>
          </div>
          {runsError && <p className="alert alert-error">{runsError}</p>}
          {runs === null && !runsError && (
            <TableSkeleton columns={["Status", "Triggered by", "Attempt", "Started", "Finished", "Result"]} rows={4} />
          )}
          {runs && runs.length === 0 && <p className="muted">No runs yet.</p>}
          {runs && runs.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Triggered by</th>
                  <th>Attempt</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>Result</th>
                  {job.job_type === "render_report" && <th />}
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <Fragment key={r.id}>
                    <tr>
                      <td>
                        <span className={`badge badge-${r.status}`}>{r.status}</span>
                      </td>
                      <td className="muted">{r.triggered_by}</td>
                      <td className="muted">{r.attempt_number}</td>
                      <td className="muted">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                      <td className="muted">{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                      <td className="muted">{r.result_summary ?? "—"}</td>
                      {job.job_type === "render_report" && (
                        <td>
                          {(r.status === "success" || r.status === "failed") && (
                            <button
                              type="button"
                              className="btn btn-sm"
                              aria-expanded={openRun === r.id}
                              onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                            >
                              {openRun === r.id ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
                              Files
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                    {openRun === r.id && (
                      <tr className="detail-row">
                        <td colSpan={7}>
                          <RunDeliveries jobId={job.id} runId={r.id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="Delete job"
        body="Scheduled firings stop within one reconcile cycle. Its run history, and the record of what each run sent, are deleted with it."
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}

const DELIVERY_BADGE: Record<JobDelivery["status"], { cls: string; label: string }> = {
  sent: { cls: "badge-success", label: "Sent" },
  saved: { cls: "badge-success", label: "Saved" },
  failed: { cls: "badge-failed", label: "Failed" },
  skipped: { cls: "badge-retrying", label: "Skipped" },
};

const size = (bytes: number | null) => (bytes === null ? "—" : bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

/** One line per file a run produced -- per value, for a job split by a filter: who it went to, whether it got
 * there, and why not. A failed email can be re-sent with the same file (kept JOB_OUTPUT_DAYS on the server). */
function RunDeliveries({ jobId, runId }: { jobId: string; runId: string }) {
  const [rows, setRows] = useState<JobDelivery[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function load() {
    api.jobs.deliveries(jobId, runId).then(setRows).catch(() => setError("Couldn't load what this run sent"));
  }
  useEffect(load, [jobId, runId]);

  async function resend() {
    setResending(true);
    setError(null);
    try {
      const { queued } = await api.jobs.resend(jobId, runId);
      setNotice(`Re-sending ${queued} email${queued === 1 ? "" : "s"}…`);
      // The worker sends them; look again shortly for the outcome.
      window.setTimeout(() => {
        load();
        setNotice(null);
      }, 4000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't re-send");
    } finally {
      setResending(false);
    }
  }

  if (error) return <p className="alert alert-error">{error}</p>;
  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <p className="muted">This run didn't record any files (it ran before delivery history existed, or failed before making one).</p>;

  const retryable = rows.filter((d) => d.can_resend).length;
  const split = rows.some((d) => d.burst_value !== null);
  return (
    <div className="stack">
      <table className="data-table">
        <thead>
          <tr>
            {split && <th>Value</th>}
            <th>Sent to</th>
            <th>Result</th>
            <th>File</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const recipients = [...d.email_to, ...d.email_cc];
            return (
              <tr key={d.id}>
                {split && (
                  <td>
                    {d.burst_label ?? d.burst_value} {d.burst_label && d.burst_label !== d.burst_value && <span className="mono muted">{d.burst_value}</span>}
                  </td>
                )}
                <td title={recipients.join(", ")}>
                  {recipients.length ? (
                    <>
                      {recipients[0]}
                      {recipients.length > 1 && <span className="muted"> +{recipients.length - 1}</span>}
                    </>
                  ) : d.saved_to ? (
                    <span className="mono muted">{d.saved_to}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  <span className={`badge ${DELIVERY_BADGE[d.status].cls}`}>{DELIVERY_BADGE[d.status].label}</span>
                  {d.sent_at && <span className="muted"> {new Date(d.sent_at).toLocaleTimeString()}</span>}
                  {d.attempts > 1 && <span className="muted"> · try {d.attempts}</span>}
                  {d.reason && <div className={d.status === "failed" ? "text-[0.78rem] text-danger" : "text-[0.78rem] text-text-faint"}>{d.reason}</div>}
                </td>
                <td className="mono muted" title={d.file_name ?? undefined}>
                  {size(d.size_bytes)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(retryable > 0 || notice) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="muted text-[0.8rem]">{notice ?? "Files are kept on the server for a while, so a re-send uses the same report."}</span>
          {retryable > 0 && (
            <button type="button" className="btn btn-sm" onClick={resend} disabled={resending || notice !== null}>
              {resending ? <span className="spinner" /> : <RotateCw size={13} aria-hidden="true" />}
              Re-send the {retryable} that failed
            </button>
          )}
        </div>
      )}
    </div>
  );
}
