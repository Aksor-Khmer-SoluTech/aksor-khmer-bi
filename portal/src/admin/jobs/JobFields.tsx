import { useState } from "react";
import JsonEditor from "../../components/JsonEditor";
import type { Job, JobType, TriggerType } from "../../types";
import type { RunForm } from "../../types";
import DeliveryFields from "./DeliveryFields";
import ReportJobFields, { type ReportJobConfig } from "./ReportJobFields";
import ScheduleField from "./ScheduleField";

/** What a job does and when -- shared by New job (JobFormDialog) and a job's Settings tab (JobDetailPanel), so the
 * two can't drift. A "Render report" job is a form (ReportJobFields); the other types keep their JSON settings,
 * in the JSON editor. The schedule is picked in words (ScheduleField) and stored as a cron expression. */

export interface JobDraft {
  jobType: JobType;
  /** render_report's settings, edited as a form. */
  reportConfig: ReportJobConfig;
  /** Every other type's settings, as JSON text. */
  configText: string;
  configValid: boolean;
  triggerType: TriggerType;
  cronExpression: string;
  intervalSeconds: number;
  /** datetime-local value, the viewer's clock. */
  runAt: string;
  /** YYYY-MM-DD */
  startDate: string;
  endDate: string;
  maxRetries: number;
  retryBackoffSeconds: number;
}

const JSON_EXAMPLES: Record<Exclude<JobType, "render_report">, object> = {
  rest_call: { url: "https://example.com/webhook", method: "POST", headers: {}, body_template: {}, context: {}, auth: null },
  soap_call: { wsdl_url: "https://example.com/service?wsdl", operation: "DoSomething", params: {}, auth: null },
  file_output: { destination_path: "/data/output/{job_id}-{timestamp}.txt", source: "static", content: "" },
  data_alert: {
    dataset: "branch-sales", values: {}, measure: "net", condition: "below", threshold: 50000000, repeat: "on_change",
    email: { connection: "company-mail", to: ["finance@example.com"] },
  },
};

const JSON_HINT: Record<Exclude<JobType, "render_report">, string> = {
  rest_call: "Calls the URL. Text in body_template can use {{ name }} from context; a secret goes in an environment variable named in auth.",
  soap_call: "Calls one operation of the SOAP service with params.",
  file_output: "Writes content to destination_path ({job_id} and {timestamp} are filled in on each run).",
  data_alert:
    "Works out a dataset measure on each run and emails when it rises above or drops below the threshold (once, until it recovers; repeat: every_time for each run). Easiest made from Analyze → Alert me.",
};

function isoToDatetimeLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function newDraft(): JobDraft {
  return {
    jobType: "render_report",
    reportConfig: { parameters: {} },
    configText: "",
    configValid: true,
    triggerType: "cron",
    cronExpression: "0 8 * * 1-5",
    intervalSeconds: 3600,
    runAt: "",
    startDate: "",
    endDate: "",
    maxRetries: 3,
    retryBackoffSeconds: 60,
  };
}

export function draftFromJob(job: Job): JobDraft {
  return {
    jobType: job.job_type,
    reportConfig: job.job_type === "render_report" ? (job.config as ReportJobConfig) : { parameters: {} },
    configText: JSON.stringify(job.config, null, 2),
    configValid: true,
    triggerType: job.trigger_type,
    cronExpression: job.cron_expression ?? "0 8 * * 1-5",
    intervalSeconds: job.interval_seconds ?? 3600,
    runAt: isoToDatetimeLocal(job.run_at),
    startDate: job.start_date ? job.start_date.slice(0, 10) : "",
    endDate: job.end_date ? job.end_date.slice(0, 10) : "",
    maxRetries: job.max_retries,
    retryBackoffSeconds: job.retry_backoff_seconds,
  };
}

/** The API's fields for a draft, or a message saying what to fix. */
export function draftToBody(d: JobDraft):
  | { error: string }
  | {
      config: Record<string, unknown>;
      trigger_type: TriggerType;
      cron_expression: string | null;
      interval_seconds: number | null;
      run_at: string | null;
      start_date: string | null;
      end_date: string | null;
      max_retries: number;
      retry_backoff_seconds: number;
    } {
  let config: Record<string, unknown>;
  if (d.jobType === "render_report") {
    if (!d.configValid) return { error: "The extra data isn't valid JSON yet" };
    if (!d.reportConfig.email && typeof d.reportConfig.destination_path !== "string") {
      return { error: "Say where the report goes: save it to a folder, email it, or both" };
    }
    // Always send `parameters`: it is what makes a run call the report's data source (an older job without it only
    // renders its saved data).
    config = { ...d.reportConfig, parameters: d.reportConfig.parameters ?? {} };
  } else {
    try {
      config = JSON.parse(d.configText);
    } catch {
      return { error: "The settings must be valid JSON" };
    }
  }
  if (d.endDate && d.startDate && d.endDate < d.startDate) return { error: "“Valid until” is before “Valid from”" };
  return {
    config,
    trigger_type: d.triggerType,
    cron_expression: d.triggerType === "cron" ? d.cronExpression : null,
    interval_seconds: d.triggerType === "interval" ? d.intervalSeconds : null,
    run_at: d.triggerType === "one_off" && d.runAt ? new Date(d.runAt).toISOString() : null,
    // A bare date is pinned to a whole day -- see UserDetailPanel.tsx's toExpiresAt for why.
    start_date: d.startDate ? `${d.startDate}T00:00:00Z` : null,
    end_date: d.endDate ? `${d.endDate}T23:59:59Z` : null,
    max_retries: d.maxRetries,
    retry_backoff_seconds: d.retryBackoffSeconds,
  };
}

const UNITS = [
  { label: "minutes", seconds: 60 },
  { label: "hours", seconds: 3600 },
  { label: "days", seconds: 86400 },
];

function IntervalField({ seconds, onChange }: { seconds: number; onChange: (s: number) => void }) {
  const [unit, setUnit] = useState(() => [...UNITS].reverse().find((u) => seconds % u.seconds === 0)?.seconds ?? 60);
  const count = Math.max(1, Math.round(seconds / unit));
  return (
    <div className="grid grid-cols-2 gap-x-4">
      <label>
        <span>Every</span>
        <input type="number" min={1} required value={count} onChange={(e) => onChange(Math.max(1, Number(e.target.value) || 1) * unit)} />
      </label>
      <label>
        <span>&nbsp;</span>
        <select
          value={unit}
          aria-label="Unit"
          onChange={(e) => {
            const next = Number(e.target.value);
            setUnit(next);
            onChange(count * next);
          }}
        >
          {UNITS.map((u) => (
            <option key={u.seconds} value={u.seconds}>
              {u.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-2.5 text-[0.72rem] font-bold tracking-[0.08em] text-text-faint uppercase">{title}</h3>
      {children}
    </section>
  );
}

const TRIGGERS: { value: TriggerType; label: string }[] = [
  { value: "cron", label: "On a schedule" },
  { value: "interval", label: "Every few minutes/hours" },
  { value: "one_off", label: "Once" },
];

export default function JobFields({
  draft,
  onChange,
  canChangeType,
}: {
  draft: JobDraft;
  onChange: (next: JobDraft) => void;
  /** A saved job keeps its type (the API doesn't change it). */
  canChangeType: boolean;
}) {
  const set = (patch: Partial<JobDraft>) => onChange({ ...draft, ...patch });
  const [form, setForm] = useState<RunForm | null>(null);

  function changeType(jobType: JobType) {
    set({
      jobType,
      configText: jobType === "render_report" ? "" : JSON.stringify(JSON_EXAMPLES[jobType], null, 2),
      configValid: true,
      reportConfig: { parameters: {} },
    });
  }

  return (
    <>
      <Section title="What it does">
        <label>
          <span>Job type</span>
          <select value={draft.jobType} disabled={!canChangeType} onChange={(e) => changeType(e.target.value as JobType)}>
            <option value="render_report">Run a report and save the file</option>
            <option value="rest_call">Call a REST API</option>
            <option value="soap_call">Call a SOAP service</option>
            <option value="file_output">Write a file</option>
            <option value="data_alert">Watch a measure (data alert)</option>
          </select>
        </label>
        {draft.jobType === "render_report" ? (
          <ReportJobFields
            config={draft.reportConfig}
            onChange={(reportConfig) => set({ reportConfig })}
            onContextValidity={(configValid) => set({ configValid })}
            onForm={setForm}
          />
        ) : (
          <div className="mb-3.5">
            <span className="field-label">Settings (JSON)</span>
            <JsonEditor value={draft.configText} onChange={(configText) => set({ configText })} rows={10} ariaLabel="Settings" />
            <p className="field-hint">{JSON_HINT[draft.jobType]}</p>
          </div>
        )}
      </Section>

      {draft.jobType === "render_report" && draft.reportConfig.report_id && (
        <DeliveryFields config={draft.reportConfig} onChange={(reportConfig) => set({ reportConfig })} form={form} reportName={form?.name ?? ""} />
      )}

      <Section title="When it runs">
        <div className="segmented mb-3.5" role="radiogroup" aria-label="Trigger">
          {TRIGGERS.map((t) => (
            <button
              key={t.value}
              type="button"
              role="radio"
              aria-checked={draft.triggerType === t.value}
              className={`segmented-btn${draft.triggerType === t.value ? " active" : ""}`}
              onClick={() => set({ triggerType: t.value })}
            >
              {t.label}
            </button>
          ))}
        </div>

        {draft.triggerType === "cron" && (
          <ScheduleField
            value={draft.cronExpression}
            onChange={(cronExpression) => set({ cronExpression })}
            startDate={draft.startDate ? `${draft.startDate}T00:00:00Z` : null}
            endDate={draft.endDate ? `${draft.endDate}T23:59:59Z` : null}
          />
        )}
        {draft.triggerType === "interval" && <IntervalField seconds={draft.intervalSeconds} onChange={(intervalSeconds) => set({ intervalSeconds })} />}
        {draft.triggerType === "one_off" && (
          <label className="sm:max-w-[50%] sm:pr-2">
            <span>Run at (your time)</span>
            <input type="datetime-local" required value={draft.runAt} onChange={(e) => set({ runAt: e.target.value })} />
          </label>
        )}

        {draft.triggerType !== "one_off" && (
          <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            <label>
              <span>
                Starting <span className="run-field-optional">(optional)</span>
              </span>
              <input type="date" value={draft.startDate} onChange={(e) => set({ startDate: e.target.value })} />
            </label>
            <label>
              <span>
                Until <span className="run-field-optional">(optional)</span>
              </span>
              <input type="date" value={draft.endDate} min={draft.startDate || undefined} onChange={(e) => set({ endDate: e.target.value })} />
            </label>
          </div>
        )}
      </Section>

      <Section title="If a run fails">
        <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
          <label>
            <span>Try again</span>
            <select value={draft.maxRetries} onChange={(e) => set({ maxRetries: Number(e.target.value) })}>
              {[0, 1, 2, 3, 5, 10].map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? "Don't retry" : `Up to ${n} time${n === 1 ? "" : "s"}`}
                </option>
              ))}
              {![0, 1, 2, 3, 5, 10].includes(draft.maxRetries) && <option value={draft.maxRetries}>Up to {draft.maxRetries} times</option>}
            </select>
          </label>
          <label>
            <span>Wait before retrying</span>
            <select value={draft.retryBackoffSeconds} disabled={draft.maxRetries === 0} onChange={(e) => set({ retryBackoffSeconds: Number(e.target.value) })}>
              {[30, 60, 300, 900, 3600].map((s) => (
                <option key={s} value={s}>
                  {s < 60 ? `${s} seconds` : s < 3600 ? `${s / 60} minute${s === 60 ? "" : "s"}` : "1 hour"}
                </option>
              ))}
              {![30, 60, 300, 900, 3600].includes(draft.retryBackoffSeconds) && <option value={draft.retryBackoffSeconds}>{draft.retryBackoffSeconds} seconds</option>}
            </select>
          </label>
        </div>
        <p className="field-hint -mt-2">Only failures that may pass are retried — a database that's down, a timeout. A wrong setting fails at once.</p>
      </Section>
    </>
  );
}
