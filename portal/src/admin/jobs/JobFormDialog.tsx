import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { useDialogRef } from "../../hooks";
import type { Job, JobType, Organization, TriggerType } from "../../types";

import ModalClose from "../../components/ModalClose";
const CONFIG_PLACEHOLDERS: Record<JobType, object> = {
  render_report: {
    report_id: "",
    format: "pdf",
    context: {},
    destination_path: "/data/output/{job_id}-{timestamp}.pdf",
  },
  rest_call: {
    url: "https://example.com/webhook",
    method: "POST",
    headers: {},
    body_template: {},
    context: {},
    auth: null,
  },
  soap_call: {
    wsdl_url: "https://example.com/service?wsdl",
    operation: "DoSomething",
    params: {},
    auth: null,
  },
  file_output: {
    destination_path: "/data/output/{job_id}-{timestamp}.txt",
    source: "static",
    content: "",
  },
};

/** Bare <input type="date"> values are pinned to a full-day ISO instant —
 * see UserDetailPanel.tsx's toExpiresAt for why a bare date can't be
 * compared directly against a timestamp. */
function toStartIso(date: string): string | null {
  return date ? `${date}T00:00:00Z` : null;
}
function toEndIso(date: string): string | null {
  return date ? `${date}T23:59:59Z` : null;
}

export default function JobFormDialog({
  open,
  onClose,
  onCreated,
  organizations,
  defaultOrgId,
  isSuperuser,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (job: Job) => void;
  organizations: Organization[];
  defaultOrgId: string;
  isSuperuser: boolean;
}) {
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [jobType, setJobType] = useState<JobType>("render_report");
  const [configText, setConfigText] = useState(JSON.stringify(CONFIG_PLACEHOLDERS.render_report, null, 2));
  const [triggerType, setTriggerType] = useState<TriggerType>("cron");
  const [cronExpression, setCronExpression] = useState("0 * * * *");
  const [intervalSeconds, setIntervalSeconds] = useState(3600);
  const [runAt, setRunAt] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [maxRetries, setMaxRetries] = useState(3);
  const [retryBackoffSeconds, setRetryBackoffSeconds] = useState(60);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const ref = useDialogRef(open, () => {
    setOrgId(defaultOrgId);
    setName("");
    setDescription("");
    setJobType("render_report");
    setConfigText(JSON.stringify(CONFIG_PLACEHOLDERS.render_report, null, 2));
    setTriggerType("cron");
    setCronExpression("0 * * * *");
    setIntervalSeconds(3600);
    setRunAt("");
    setStartDate("");
    setEndDate("");
    setIsEnabled(true);
    setMaxRetries(3);
    setRetryBackoffSeconds(60);
    setError(null);
  });

  function changeJobType(next: JobType) {
    setJobType(next);
    setConfigText(JSON.stringify(CONFIG_PLACEHOLDERS[next], null, 2));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText);
    } catch {
      setError("Config must be valid JSON");
      return;
    }

    setPending(true);
    try {
      const job = await api.jobs.create(orgId, {
        name,
        description: description || null,
        job_type: jobType,
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
      onCreated(job);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the job");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal" onCancel={onClose}>
      <ModalClose />
      <h2 className="panel-title">New job</h2>
      <p className="panel-subtitle">Runs by schedule, or on demand from its detail panel or the API.</p>
      <form onSubmit={handleSubmit}>
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

        {isSuperuser && (
          <label>
            <span>Organization</span>
            <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <label>
          <span>Job type</span>
          <select value={jobType} onChange={(e) => changeJobType(e.target.value as JobType)}>
            <option value="render_report">Render report</option>
            <option value="rest_call">REST call</option>
            <option value="soap_call">SOAP call</option>
            <option value="file_output">File output</option>
          </select>
        </label>

        <label>
          <span>Config (JSON)</span>
          <textarea className="mono-input" value={configText} onChange={(e) => setConfigText(e.target.value)} spellCheck={false} />
          <p className="field-hint">
            {"{job_id}"} and {"{timestamp}"} are substituted in destination_path so repeated firings don't overwrite each other.
          </p>
        </label>

        <div className="row">
          <label>
            <span>Trigger</span>
            <select value={triggerType} onChange={(e) => setTriggerType(e.target.value as TriggerType)}>
              <option value="cron">Cron schedule</option>
              <option value="interval">Fixed interval</option>
              <option value="one_off">One-off, at a specific time</option>
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
        {triggerType === "cron" && (
          <p className="field-hint">5-field crontab: minute hour day-of-month month day-of-week. "0 * * * *" = every hour.</p>
        )}

        <div className="row">
          <label>
            <span>Valid from (optional)</span>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            <span>Valid until (optional)</span>
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

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Create job
          </button>
        </div>
      </form>
    </dialog>
  );
}
