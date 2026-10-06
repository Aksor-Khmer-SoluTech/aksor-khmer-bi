import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { FORMATS_BY_EXT, type BatchLimits, type RenderFormat, type ReportMeta } from "../types";

/** "about 45 s" / "about 3 min" -- a rough expectation, not a promise. */
function about(seconds: number): string {
  if (seconds < 1) return "under a second";
  if (seconds < 90) return `about ${Math.round(seconds)} s`;
  return `about ${Math.round(seconds / 60)} min`;
}

/** How many records the JSON currently holds, or null if it isn't a valid array yet. */
function countRecords(text: string): number | null {
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.length : null;
  } catch {
    return null;
  }
}

export default function BatchRender() {
  const [reports, setReports] = useState<ReportMeta[]>([]);
  const [reportId, setReportId] = useState<string>("");
  const [format, setFormat] = useState<RenderFormat>("pdf");
  const [text, setText] = useState('[\n  {},\n  {}\n]');
  const [limits, setLimits] = useState<BatchLimits | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    api.listReports().then((r) => {
      setReports(r);
      if (r.length > 0) {
        setReportId(r[0].report_id);
        setFormat(FORMATS_BY_EXT[r[0].template_ext][0]);
      }
    });
    // The server owns these numbers (they're settings, and differ by format);
    // if they can't be fetched the page still works -- the server enforces them.
    api.batchLimits().then(setLimits).catch(() => setLimits(null));
  }, []);

  const selected = reports.find((r) => r.report_id === reportId) ?? null;

  const records = useMemo(() => countRecords(text), [text]);
  const cap = limits?.max_records[format] ?? null;
  const perRecord = limits?.seconds_per_record[format] ?? null;
  const overCap = records !== null && cap !== null && records > cap;
  // The cheap formats are worth pointing at when the expensive ones are the ones that hit the wall.
  const cheapCap = limits ? Math.max(limits.max_records.docx, limits.max_records.xlsx) : null;
  const slowFormat = limits ? limits.seconds_per_record[format] >= 1 : false;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!selected) return;

    let contexts: Record<string, unknown>[];
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) throw new Error("Expected a JSON array of context objects");
      contexts = parsed;
    } catch (err) {
      setError(`Contexts must be valid JSON: ${(err as Error).message}`);
      return;
    }
    if (contexts.length === 0) {
      setError("Add at least one context object to the array.");
      return;
    }
    if (cap !== null && contexts.length > cap) return; // the estimate line already says why

    setPending(true);
    try {
      const { blob, filename } = await api.renderBatch(selected.report_id, contexts, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setSuccess(`Rendered ${contexts.length} document(s) — downloading ${filename}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Batch render failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Batch render</h1>
          <p className="page-subtitle">
            Render one template against many records in a single request — a ZIP comes back.
            {limits ? (
              <>
                {" "}
                PDF and PNG take about {limits.seconds_per_record.pdf} s per record, so they're limited to{" "}
                {limits.max_records.pdf} per run; DOCX and XLSX are near-instant and allow up to{" "}
                {limits.max_records.docx.toLocaleString()}. It all happens in one request, so there's no progress bar —
                keep PDF runs small.
              </>
            ) : (
              " It all happens in one request, so there's no progress bar."
            )}
          </p>
        </div>
      </div>

      <div className="panel">
        <form onSubmit={handleSubmit}>
          <div className="row">
            <label>
              <span>Template</span>
              <select
                value={reportId}
                onChange={(e) => {
                  setReportId(e.target.value);
                  const r = reports.find((x) => x.report_id === e.target.value);
                  if (r) setFormat(FORMATS_BY_EXT[r.template_ext][0]);
                }}
              >
                {reports.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ flex: "0 0 140px" }}>
              <span>Format</span>
              <select value={format} onChange={(e) => setFormat(e.target.value as RenderFormat)}>
                {(selected ? FORMATS_BY_EXT[selected.template_ext] : ["pdf"]).map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            <span>Contexts (JSON array)</span>
            <textarea className="mono-input json-editor" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
          </label>

          {/* What this run will cost, before sending it: the count, roughly how
              long, and -- if it's over the limit for this format -- why not. */}
          {records !== null && limits && (
            <p className={`batch-estimate${overCap ? " batch-estimate-over" : ""}`} role="status" aria-live="polite">
              {overCap ? (
                <>
                  <strong>{records.toLocaleString()} records</strong> is over the limit of {cap!.toLocaleString()} for{" "}
                  {format.toUpperCase()} (each takes {about(perRecord!)}, all in one request). Split it into runs of up to{" "}
                  {cap!.toLocaleString()}
                  {slowFormat && cheapCap ? `, or use DOCX/XLSX, which allow up to ${cheapCap.toLocaleString()}` : ""}.
                </>
              ) : (
                <>
                  <strong>
                    {records.toLocaleString()} {records === 1 ? "record" : "records"}
                  </strong>{" "}
                  · {records > 0 ? about(records * perRecord!) : "nothing to render"} ({format.toUpperCase()} takes {about(perRecord!)} each,
                  limit {cap!.toLocaleString()} per run)
                </>
              )}
            </p>
          )}

          {error && <p className="alert alert-error">{error}</p>}
          {success && <p className="alert alert-success">{success}</p>}
          <button type="submit" className="btn btn-primary" disabled={pending || !selected || overCap}>
            {pending && <span className="spinner" />}
            Render batch → download ZIP
          </button>
        </form>
      </div>
    </div>
  );
}
