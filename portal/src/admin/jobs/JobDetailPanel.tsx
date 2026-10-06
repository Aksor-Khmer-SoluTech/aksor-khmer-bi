import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { TableSkeleton } from "../../components/Skeletons";
import type { Job, JobRun, TriggerType } from "../../types";

type Tab = "settings" | "runs";

function isoToDatetimeLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isoToDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

function toStartIso(date: string): string | null {
  return date ? `${date}T00:00:00Z` : null;
}
function toEndIso(date: string): string | null {
  return date ? `${date}T23:59:59Z` : null;
}

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
  const [configText, setConfigText] = useState(JSON.stringify(job.config, null, 2));
  const [triggerType, setTriggerType] = useState<TriggerType>(job.trigger_type);
  const [cronExpression, setCronExpression] = useState(job.cron_expression ?? "0 * * * *");
  const [intervalSeconds, setIntervalSeconds] = useState(job.interval_seconds ?? 3600);
  const [runAt, setRunAt] = useState(isoToDatetimeLocal(job.run_at));
  const [startDate, setStartDate] = useState(isoToDateInput(job.start_date));
  const [endDate, setEndDate] = useState(isoToDateInput(job.end_date));
  const [isEnabled, setIsEnabled] = useState(job.is_enabled);
  const [maxRetries, setMaxRetries] = useState(job.max_retries);
  const [retryBackoffSeconds, setRetryBackoffSeconds] = useState(job.retry_backoff_seconds);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [runs, setRuns] = useState<JobRun[] | null>(null);
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

    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText);
    } catch {
      setSettingsError("Config must be valid JSON");
      return;
    }

    setSavingSettings(true);
    try {
      const updated = await api.jobs.update(job.id, {
        name,
        description: description || null,
        config,
        trigger_type: triggerType,
        cron_expression: triggerType === "cron" ? cronExpression : null,
        interval_seconds: triggerType === "interval" ? intervalSeconds : null,
        run_at: triggerType === "one_off" && runAt ? new Date(runAt).toISOString() : null,
        start_date: toStartIso(startDate),
        end_date: toEndIso(endDate),
        is_enabled: isEnabled,
        max_retries: maxRetries,
        retry_backoff_seconds: retryBackoffSeconds,
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

          <label>
            <span>Config (JSON)</span>
            <textarea className="mono-input" value={configText} onChange={(e) => setConfigText(e.target.value)} spellCheck={false} />
          </label>

          <div className="row">
            <label>
              <span>Trigger</span>
              <select value={triggerType} onChange={(e) => setTriggerType(e.target.value as TriggerType)}>
                <option value="cron">Cron schedule</option>
                <option value="interval">Fixed interval</option>
                <option value="one_off">One-off</option>
              </select>
            </label>
            {triggerType === "cron" && (
              <label>
                <span>Cron expression</span>
                <input type="text" required value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} className="mono" />
              </label>
            )}
            {triggerType === "interval" && (
              <label>
                <span>Interval (seconds)</span>
                <input
                  type="number"
                  required
                  min={1}
                  value={intervalSeconds}
                  onChange={(e) => setIntervalSeconds(Number(e.target.value))}
                />
              </label>
            )}
            {triggerType === "one_off" && (
              <label>
                <span>Run at</span>
                <input type="datetime-local" required value={runAt} onChange={(e) => setRunAt(e.target.value)} />
              </label>
            )}
          </div>

          <div className="row">
            <label>
              <span>Valid from</span>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label>
              <span>Valid until</span>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
          </div>

          <div className="row">
            <label>
              <span>Max retries</span>
              <input type="number" min={0} value={maxRetries} onChange={(e) => setMaxRetries(Number(e.target.value))} />
            </label>
            <label>
              <span>Retry backoff (seconds)</span>
              <input
                type="number"
                min={0}
                value={retryBackoffSeconds}
                onChange={(e) => setRetryBackoffSeconds(Number(e.target.value))}
              />
            </label>
          </div>

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
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className={`badge badge-${r.status}`}>{r.status}</span>
                    </td>
                    <td className="muted">{r.triggered_by}</td>
                    <td className="muted">{r.attempt_number}</td>
                    <td className="muted">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                    <td className="muted">{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                    <td className="muted">{r.result_summary ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="Delete job"
        body="Scheduled firings stop within one reconcile cycle; run history is kept."
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}
