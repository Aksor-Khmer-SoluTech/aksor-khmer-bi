import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api";
import JsonEditor from "../../components/JsonEditor";
import type { AccessibleReport, RenderFormat, RunForm, RunFormParameter } from "../../types";

/** A "Render report" job's settings as a form instead of JSON: which report, in which format, its filters (the run
 * page's, so a scheduled run asks the report's own data source for exactly what a person would), and -- tucked
 * away -- extra data laid over what the source returns. Where the file goes, and splitting it by a filter, is
 * DeliveryFields' part of the same config. Edits `config` in place:
 *
 *   { report_id, format, parameters: {name: value}, context?, ...DeliveryFields' }
 *
 * A filter left empty is left out of `parameters`, so the server applies its default when the job runs -- a date
 * filter defaulting to now() is the day it fires. The server re-checks all of it on save, against the creator's own
 * access (routers/jobs.py). */

export type ReportJobConfig = {
  report_id?: string;
  format?: string;
  parameters?: Record<string, string>;
  destination_path?: string;
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

const FORMAT_LABEL: Record<RenderFormat, string> = {
  pdf: "PDF document",
  docx: "Word document (.docx)",
  xlsx: "Excel workbook (.xlsx)",
  png: "Image (.png)",
};

const slug = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "report";

function defaultPath(report: { name: string }, format: string) {
  return `/data/output/${slug(report.name)}-{timestamp}.${format}`;
}

function defaultNote(p: RunFormParameter): string | null {
  const d = p.default_value;
  if (!d) return null;
  if (d === "now()") return p.type === "time" ? "the time it runs" : p.type === "datetime" ? "the moment it runs" : "the day it runs";
  if (d === "firstDayOfMonth()") return "the first day of the month it runs in";
  if (d === "lastDayOfMonth()") return "the last day of the month it runs in";
  return d;
}

const INPUT_TYPE: Record<string, string> = { text: "text", number: "number", date: "date", time: "time", datetime: "datetime-local" };

function FilterField({ parameter, value, onChange }: { parameter: RunFormParameter; value: string; onChange: (v: string) => void }) {
  const label = parameter.label ?? parameter.name;
  const fallback = defaultNote(parameter);
  // Required unless leaving it empty means something: its default, or (optional text) nothing.
  const required = parameter.required && !fallback;
  return (
    <label>
      <span>
        {label} {required ? <span className="required-mark" aria-hidden="true">*</span> : <span className="run-field-optional">(optional)</span>}
      </span>
      {parameter.options ? (
        <select value={value} required={required} onChange={(e) => onChange(e.target.value)}>
          <option value="" disabled={required}>
            {fallback ? `Default — ${fallback}` : required ? "Choose…" : "None"}
          </option>
          {parameter.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label ? `${o.label} (${o.value})` : o.value}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={INPUT_TYPE[parameter.type] ?? "text"}
          step={parameter.type === "number" ? "any" : undefined}
          required={required}
          value={value}
          placeholder={fallback ? `Empty: ${fallback}` : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {fallback && !parameter.options && <span className="run-field-note">Leave empty for {fallback}.</span>}
    </label>
  );
}

export default function ReportJobFields({
  config,
  onChange,
  onContextValidity,
  onForm,
}: {
  config: ReportJobConfig;
  onChange: (next: ReportJobConfig) => void;
  /** The chosen report's run form, for DeliveryFields (which filters it can be split by). */
  onForm?: (form: RunForm | null) => void;
  /** Whether the extra-data JSON parses -- the dialog won't save until it does. */
  onContextValidity: (valid: boolean) => void;
}) {
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const [form, setForm] = useState<RunForm | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [contextText, setContextText] = useState(() =>
    config.context && Object.keys(config.context).length > 0 ? JSON.stringify(config.context, null, 2) : ""
  );
  const [contextError, setContextError] = useState<string | null>(null);
  // An older job: data saved in it, no filters -- it renders that data and never calls the report's source.
  const [legacy] = useState(() => config.parameters === undefined && !!config.context && Object.keys(config.context).length > 0);

  useEffect(() => {
    api
      .listAccessibleReports()
      .then((all) => setReports(all.filter((r) => r.access_level !== "view" && !r.is_draft)))
      .catch(() => setReports([]));
  }, []);

  const reportId = config.report_id ?? "";
  useEffect(() => {
    setForm(null);
    onForm?.(null);
    setFormError(null);
    if (!reportId) return;
    let cancelled = false;
    api
      .getRunForm(reportId)
      .then((f) => {
        if (cancelled) return;
        setForm(f);
        onForm?.(f);
      })
      .catch((err) => !cancelled && setFormError(err instanceof ApiError ? err.message : "Couldn't load that report's filters"));
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const selected = useMemo(() => reports?.find((r) => r.report_id === reportId) ?? null, [reports, reportId]);

  function chooseReport(id: string) {
    const report = reports?.find((r) => r.report_id === id);
    const format = report?.template_ext === "xlsx" ? "xlsx" : "pdf";
    // Another report has other filters: a split by the old one's filter no longer means anything.
    const { burst: _drop, ...rest } = config;
    onChange({
      ...rest,
      report_id: id,
      format,
      parameters: {},
      ...(config.destination_path !== undefined || !config.email ? { destination_path: report ? defaultPath(report, format) : config.destination_path } : {}),
    });
  }

  function chooseFormat(format: string) {
    const old = config.format;
    const path = config.destination_path ?? "";
    // Keep the file's extension in step with the format, unless someone wrote their own.
    const destination_path = old && path.endsWith(`.${old}`) ? `${path.slice(0, -old.length)}${format}` : path;
    onChange({ ...config, format, destination_path });
  }

  function setParameter(name: string, value: string) {
    const parameters = { ...(config.parameters ?? {}) };
    if (value === "") delete parameters[name];
    else parameters[name] = value;
    onChange({ ...config, parameters });
  }

  function setContext(text: string) {
    setContextText(text);
    if (!text.trim()) {
      setContextError(null);
      onContextValidity(true);
      const { context: _drop, ...rest } = config;
      onChange(rest);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not an object");
      setContextError(null);
      onContextValidity(true);
      onChange({ ...config, context: parsed });
    } catch {
      setContextError('Write a JSON object, like {"note": "Monthly close"}');
      onContextValidity(false);
    }
  }

  const formats = form?.formats ?? (selected ? (selected.template_ext === "xlsx" ? ["xlsx"] : ["pdf", "png", "docx", "xlsx"]) : []);
  const ext = form?.template_ext ?? selected?.template_ext;

  return (
    <>
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <label>
          <span>
            Report <span className="required-mark" aria-hidden="true">*</span>
          </span>
          <select required value={reportId} onChange={(e) => chooseReport(e.target.value)} disabled={reports === null}>
            <option value="" disabled>
              {reports === null ? "Loading reports…" : reports.length === 0 ? "No reports you can run" : "Choose a report…"}
            </option>
            {reportId && reports && !selected && <option value={reportId}>{reportId}</option>}
            {reports?.map((r) => (
              <option key={r.report_id} value={r.report_id}>
                {r.folder_path.length > 0 ? `${r.folder_path.map((f) => f.name).join(" / ")} / ` : ""}
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Format</span>
          <select value={config.format ?? ""} onChange={(e) => chooseFormat(e.target.value)} disabled={!reportId}>
            {formats.map((f) => (
              <option key={f} value={f}>
                {f === "xlsx" && ext === "docx" ? "Excel tables (.xlsx)" : FORMAT_LABEL[f as RenderFormat]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {formError && <p className="alert alert-error">{formError}</p>}
      {form && legacy && form.has_data_source && (
        <p className="alert alert-warning">
          This job renders data saved in it (under Extra data) instead of calling the report's data source. Saving it from here switches it to the
          report's own data, with the filters below.
        </p>
      )}
      {form && form.parameters.length > 0 && (
        <fieldset className="mb-3.5 rounded-sm border border-border-soft px-4 pt-3 pb-0.5">
          <legend className="px-1 text-[0.78rem] font-medium text-text-dim">Filters for each run</legend>
          <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            {form.parameters.map((p) =>
              (config.burst as { by?: string } | undefined)?.by === p.name ? (
                <div key={p.name} className="run-field">
                  <span className="field-label">{p.label ?? p.name}</span>
                  <p className="m-0 rounded-sm bg-bg-panel px-3 py-2.5 text-[0.82rem] text-text-dim">Each value in turn — the job is split by it (below).</p>
                </div>
              ) : (
                <FilterField key={p.name} parameter={p} value={config.parameters?.[p.name] ?? ""} onChange={(v) => setParameter(p.name, v)} />
              )
            )}
          </div>
        </fieldset>
      )}
      {form && form.parameters.length === 0 && form.has_data_source && (
        <p className="field-hint -mt-1 mb-3.5">This report has no filters: every run fetches the same query's latest data.</p>
      )}

      {form && (
        <details className="mb-3.5" open={!form.has_data_source || contextText !== ""}>
          <summary className="cursor-pointer text-[0.82rem] text-text-dim select-none">
            {form.has_data_source ? "Extra data (optional)" : "Data for the report"}
          </summary>
          <p className="field-hint mt-2 mb-2">
            {form.has_data_source
              ? "JSON laid over what the data source returns — for a value the template needs that the source doesn't give."
              : "This report has no data source, so each run renders this JSON."}
          </p>
          <JsonEditor value={contextText} onChange={setContext} invalid={!!contextError} rows={8} placeholder='{ "title": "Monthly sales" }' ariaLabel="Extra data" />
          {contextError && <p className="field-hint text-danger">{contextError}</p>}
        </details>
      )}
    </>
  );
}
