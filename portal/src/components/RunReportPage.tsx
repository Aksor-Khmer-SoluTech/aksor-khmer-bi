import { lazy, Suspense, useEffect, useId, useState, type FormEvent } from "react";
import { ArrowLeft, FileText, Lock, Play, SlidersHorizontal } from "lucide-react";
import { api, ApiError } from "../api";
import { initialValue } from "../dateFormat";
import { downloadBlob } from "../download";
import DateTimeField from "./DateTimeField";
import { ReportViewerShell } from "./ReportSkeleton";
import type { ParameterType, RenderFormat, RunForm, RunFormParameter } from "../types";

// pdf.js is heavy and most sessions never open a report -- same lazy
// boundary TemplateDetail's Preview tab and EmbedPage already use.
const ReportViewer = lazy(() => import("./ReportViewer"));

const VALUE_MAX = 200;
// ReportViewer refetches whenever its contextData *reference* changes, and
// here the data comes from the server (via `renderer`), not from this prop
// -- so hand it one stable empty object rather than a fresh `{}` per render.
const NO_CONTEXT: Record<string, unknown> = {};

// A free-text parameter's declared type picks its control: text and number
// are native inputs; date, time and date-time are DateTimeField, which shows
// them in the portal's standard display format (PORTAL_DATE_FORMAT & co. in
// config.js) rather than the browser's locale. Either way the value it holds
// is the same YYYY-MM-DD / HH:MM / YYYY-MM-DDTHH:MM string a native control
// would produce, which is what app/report_data.py's _value_matches_type expects.
const HTML_INPUT_TYPE: Record<"text" | "number", string> = { text: "text", number: "number" };

const isTemporal = (type: ParameterType): type is "date" | "time" | "datetime" =>
  type === "date" || type === "time" || type === "datetime";

/** One filter control. A choice list narrowed to a single value is shown
 * locked rather than as a one-item dropdown: the user should see *why*
 * they can't pick anything else, not wonder if the page is broken. */
function ParameterField({
  parameter,
  value,
  onChange,
}: {
  parameter: RunFormParameter;
  value: string;
  onChange: (next: string) => void;
}) {
  const labelId = useId();
  const label = parameter.label ?? parameter.name;
  const options = parameter.options;
  // The native `required` attribute carries real semantics (browser
  // validation, the accessibility tree) beyond the visual mark below --
  // belt and suspenders, not just styling.
  const labelContent = (
    <>
      {label}{" "}
      {parameter.required ? (
        <span className="required-mark" aria-hidden="true">*</span>
      ) : (
        <span className="run-field-optional">(optional)</span>
      )}
    </>
  );

  if (options === null && isTemporal(parameter.type)) {
    // Not a <label>: its popover lives inside this element, and a click on the
    // popover's own padding would otherwise be forwarded to the input as a label click.
    return (
      <div className="run-field">
        <span className="field-label" id={labelId}>
          {labelContent}
        </span>
        <DateTimeField kind={parameter.type} value={value} onChange={onChange} required={parameter.required} labelledBy={labelId} />
      </div>
    );
  }

  if (options === null) {
    return (
      <label>
        <span>{labelContent}</span>
        <input
          type={HTML_INPUT_TYPE[parameter.type as "text" | "number"]}
          maxLength={parameter.type === "text" ? VALUE_MAX : undefined}
          step={parameter.type === "number" ? "any" : undefined}
          required={parameter.required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }

  if (options.length === 0) {
    return (
      <label>
        <span>{labelContent}</span>
        <select disabled value="">
          <option value="">Nothing available</option>
        </select>
        <span className="run-field-note run-field-note-warn">
          None of this filter's values are available to you. Ask an administrator for access.
        </span>
      </label>
    );
  }

  const locked = options.length === 1;
  return (
    <label>
      <span>{labelContent}</span>
      <select value={value} disabled={locked} required onChange={(e) => onChange(e.target.value)}>
        {!locked && (
          <option value="" disabled>
            Choose…
          </option>
        )}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label ? `${o.label} (${o.value})` : o.value}
          </option>
        ))}
      </select>
      {locked && (
        <span className="run-field-note">
          <Lock size={12} aria-hidden="true" /> Your access is limited to this {label.toLowerCase()}.
        </span>
      )}
    </label>
  );
}

/** Where a signed-in user opens and runs one report from the Reports page:
 * a form of its filter parameters -- whose choice lists arrive already
 * narrowed to what their grants allow -- and the result. Every render,
 * including each export-menu format, goes through the authenticated /run
 * route, which re-checks the values server-side before it fetches any data;
 * nothing here is the enforcement, it just reflects it. */
export default function RunReportPage({ reportId, onBack }: { reportId: string; onBack: () => void }) {
  const [form, setForm] = useState<RunForm | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<Record<string, string> | null>(null);
  const [runId, setRunId] = useState(0);
  const [downloading, setDownloading] = useState(false);
  // A preview run is in flight: from the click until the viewer reports it
  // has settled (rendered or failed). Covers the lazy chunk still loading,
  // when the viewer isn't mounted yet to say anything itself.
  const [previewing, setPreviewing] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const busy = previewing || downloading;

  useEffect(() => {
    setForm(null);
    setLoadError(null);
    setSubmitted(null);
    setPreviewing(false);
    api
      .getRunForm(reportId)
      .then((f) => {
        setForm(f);
        // A single permitted value is preselected (and shown locked); a free-text
        // parameter starts with its default, `now()` read from this browser's clock.
        setValues(
          Object.fromEntries(
            f.parameters.map((p) => [p.name, p.options ? (p.options.length === 1 ? p.options[0].value : "") : initialValue(p.type, p.default_value)])
          )
        );
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Couldn't open this report"));
  }, [reportId]);

  const canPreview = form?.formats.includes("pdf") ?? false;

  // The viewer (and pdf.js with it) is a big lazy chunk. Start fetching it
  // as soon as we know this report previews -- while the user is still
  // choosing filters -- so clicking Run finds it already there instead of
  // waiting on a download before anything can render.
  useEffect(() => {
    if (canPreview) void import("./ReportViewer");
  }, [canPreview]);

  const complete =
    form !== null &&
    form.parameters.every(
      (p) => !p.required || ((p.options === null || p.options.length > 0) && (values[p.name] ?? "") !== ""),
    );
  const dirty = submitted !== null && form !== null && form.parameters.some((p) => submitted[p.name] !== values[p.name]);

  async function run(e: FormEvent) {
    e.preventDefault();
    // The disabled button already blocks a second click, but Enter in a
    // filter field submits the form too -- so the handler refuses as well.
    if (!form || !complete || busy) return;
    setRunError(null);
    const snapshot = { ...values };
    if (canPreview) {
      setPreviewing(true);
      setSubmitted(snapshot);
      setRunId((n) => n + 1);
      return;
    }
    // A template with no PDF path (xlsx) has nothing to page through:
    // run it and hand back the file.
    const format: RenderFormat = form.formats[0];
    setDownloading(true);
    try {
      const { blob, filename } = await api.runReport(reportId, snapshot, format, form.name);
      downloadBlob(blob, filename);
      setSubmitted(snapshot);
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : "Couldn't run this report");
    } finally {
      setDownloading(false);
    }
  }

  // Only built once `form` is truthy (short-circuit narrows it for
  // TypeScript within this expression) -- the sidebar's own contents,
  // shared between the two-column preview layout and the plain single
  // panel a non-preview (xlsx) template falls back to.
  const filterSidebar = form && (
    <form className="panel run-sidebar" onSubmit={run}>
      <button type="submit" className="btn btn-primary run-sidebar-submit" disabled={!complete || busy} aria-busy={busy}>
        {busy ? <span className="spinner" /> : <Play size={14} aria-hidden="true" />}
        {busy ? "Running…" : canPreview ? "Run report" : "Run and download"}
      </button>
      {dirty && <span className="muted run-sidebar-note">Filters changed — run again to update.</span>}
      {runError && <p className="alert alert-error run-sidebar-note">{runError}</p>}

      {form.parameters.length > 0 && (
        <>
          <div className="run-filter-head-label run-sidebar-label">
            <SlidersHorizontal size={13} aria-hidden="true" />
            Filters
          </div>
          <div className="run-fields-vertical">
            {form.parameters.map((p) => (
              <ParameterField
                key={p.name}
                parameter={p}
                value={values[p.name] ?? ""}
                onChange={(next) => setValues((prev) => ({ ...prev, [p.name]: next }))}
              />
            ))}
          </div>
        </>
      )}
    </form>
  );

  // The rendered report itself, shown in the preview pane beside the filter
  // sidebar once a run has been submitted.
  const viewer =
    form && submitted ? (
      <Suspense fallback={<ReportViewerShell />}>
        <ReportViewer
          reportId={form.report_id}
          reportName={form.name}
          templateExt={form.template_ext}
          contextData={NO_CONTEXT}
          renderer={(format, part) => api.runReport(form.report_id, submitted, format, form.name, part)}
          // A re-run refreshes this same viewer rather than remounting it,
          // so the old page stays up (dimmed) and zoom survives the run.
          refreshKey={runId}
          onBusyChange={setPreviewing}
        />
      </Suspense>
    ) : null;

  return (
    <div className="run-page">
      {/* One compact row -- back link, title, description -- rather than a
          breadcrumb row above a full-size title block: on a small monitor
          that stack pushed the report a hundred pixels down the screen,
          and the breadcrumb's last crumb only repeated the title anyway.
          The back link renders straight away; only the title waits on the
          form. */}
      <div className="page-header page-header-compact">
        <button type="button" className="run-back" onClick={onBack} aria-label="Back to Reports">
          <ArrowLeft size={15} aria-hidden="true" />
          Reports
        </button>
        {form ? (
          <div className="page-header-text">
            <h1 className="page-title">{form.name}</h1>
            {form.description && (
              <p className="page-subtitle" title={form.description}>
                {form.description}
              </p>
            )}
          </div>
        ) : (
          !loadError && (
            <div className="page-header-text run-skel-head" aria-hidden="true">
              <div className="skel run-skel-title" />
              <div className="skel run-skel-subtitle" />
            </div>
          )
        )}
      </div>

      {loadError && <p className="alert alert-error">{loadError}</p>}
      {!form && !loadError && (
        // Mirrors the real page below -- the same `.run-layout` grid
        // (filters panel + preview pane) -- so nothing reflows when the
        // form arrives. The filter count isn't known yet, so it shows the
        // typical few fields.
        <div className="run-loading-skeleton" role="status" aria-live="polite">
          <span className="sr-only">Opening report…</span>
          <div className="run-layout" aria-hidden="true">
            <div className="panel run-sidebar">
              <div className="skel run-skel-button" />
              <div className="run-skel-fields">
                <div className="skel run-skel-heading" />
                {[0, 1, 2].map((i) => (
                  <div key={i} className="run-skel-field">
                    <div className="skel run-skel-label" />
                    <div className="skel run-skel-input" />
                  </div>
                ))}
              </div>
            </div>
            <div className="skel run-skel-preview" />
          </div>
        </div>
      )}

      {form && (
        <>
          {canPreview ? (
            // JasperReports-style: filters as a sticky left column (Run
            // report pinned at its top, fields stacked below) beside the
            // rendered report, instead of a form sitting above it. Used
            // for every previewable report -- including ones with no
            // filters, where the sidebar just says so -- so a report
            // always renders in the same place.
            <div className="run-layout">
              {filterSidebar}
              {submitted ? (
                <div className="run-result">{viewer}</div>
              ) : (
                <div className="run-result-empty">
                  <FileText size={36} strokeWidth={1.4} aria-hidden="true" />
                  <p>
                    {form.parameters.length === 0
                      ? "Run the report to preview it here."
                      : "Set your filters, then run the report to preview it here."}
                  </p>
                </div>
              )}
            </div>
          ) : form.parameters.length === 0 ? (
            // No PDF path (xlsx) and nothing to configure -- there's no
            // preview to sit beside, so just the Run button in a slim row
            // beats a whole sidebar for a single button.
            <form className="panel run-form run-form-compact" onSubmit={run}>
              <div className="run-bar">
                <button type="submit" className="btn btn-primary" disabled={!complete || busy} aria-busy={busy}>
                  {busy ? <span className="spinner" /> : <Play size={14} aria-hidden="true" />}
                  {busy ? "Running…" : "Run and download"}
                </button>
              </div>
              {runError && <p className="alert alert-error">{runError}</p>}
            </form>
          ) : (
            // No PDF path (xlsx) -- nothing to preview beside, so the
            // sidebar shape stands alone as a single panel.
            filterSidebar
          )}
        </>
      )}
    </div>
  );
}
