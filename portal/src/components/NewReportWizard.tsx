import { Cable, Check, Copy, Database, Download, FileText, FlaskConical, Play, TriangleAlert, Upload, UploadCloud } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { has } from "../admin/sections";
import { api, ApiError } from "../api";
import { EMPTY_SOURCE, parseStaticData, toDataSource, type EditableSource } from "../dataConfig";
import { downloadBlob } from "../download";
import type { Route } from "../hooks";
import { suggestCode } from "../reportCode";
import type { AuthInfo, ConnectionSummary, DataField, DataPreview, DataSourceType, ParameterType, ReportMeta, ReportParameter, TemplateCheck, TemplateExt } from "../types";
import FolderPicker from "./FolderPicker";
import JdbcSourceFields from "./JdbcSourceFields";
import ReportCodeField from "./ReportCodeField";
import RequestFields from "./RequestFields";
import RunReportPage from "./RunReportPage";
import StaticSourceFields from "./StaticSourceFields";

type Step = 1 | 2 | 3 | 4;

const STEPS: { n: Step; label: string; sub: string }[] = [
  { n: 1, label: "Data", sub: "Where it comes from" },
  { n: 2, label: "Fields", sub: "Placeholders & starter file" },
  { n: 3, label: "Design", sub: "Upload your layout" },
  { n: 4, label: "Preview & publish", sub: "Test with real data" },
];

const KINDS: { id: DataSourceType; label: string; blurb: string; icon: typeof Cable }[] = [
  { id: "static", label: "Sample JSON", blurb: "Paste an example to design against; connect real data later.", icon: FlaskConical },
  { id: "rest", label: "REST API", blurb: "A saved connection plus a path, or a full URL. Filters go in as {{ name }}.", icon: Cable },
  { id: "jdbc", label: "Database", blurb: "A saved connection plus a SQL query. Filters go in as :name.", icon: Database },
];

const FILTER_TYPES: ParameterType[] = ["text", "number", "date", "datetime", "time"];
const INPUT_TYPE: Record<ParameterType, string> = { text: "text", number: "number", date: "date", datetime: "datetime-local", time: "time" };
const STARTER_TYPES: TemplateExt[] = ["docx", "xlsx", "html"];
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

// --- writing placeholders for a field (mirrors api/app/report_wizard.py's starter, so they agree) -------------------

function loopName(listPath: string): string {
  const base = listPath.split(".").pop()!.replace(/\[\]$/, "");
  let name = "item";
  if (base.endsWith("ies") && base.length > 4) name = base.slice(0, -3) + "y";
  else if (base.endsWith("s") && base.length > 3 && !base.endsWith("ss")) name = base.slice(0, -1);
  return IDENT.test(name) && name !== base ? name : "row";
}

const access = (base: string, key: string) => (IDENT.test(key) ? `${base}.${key}` : `${base}["${key}"]`);

/** How a template writes `path` -- `invoices[].total_usd` inside its loop is `invoice.total_usd`. */
function expressionFor(path: string): string {
  const parts = path.split(/\.(?![^[]*\])/);
  let expr = "";
  let listPath = "";
  for (const part of parts) {
    const isItems = part.endsWith("[]");
    const key = part.replace(/\[\]$/, "");
    if (!expr) expr = key;
    else expr = access(expr, key);
    listPath = listPath ? `${listPath}.${part}` : part;
    if (isItems) expr = loopName(listPath);
  }
  return expr;
}

function listOf(path: string): string | null {
  const i = path.lastIndexOf("[]");
  return i === -1 ? null : path.slice(0, i);
}

interface Snippet {
  title: string;
  code: string;
  hint: ReactNode;
}

function snippetFor(field: DataField, fields: DataField[], ext: TemplateExt, isFilter: boolean): Snippet {
  const expr = expressionFor(field.path);
  const inLoop = listOf(field.path);
  const loopHint = inLoop ? (
    <>
      Inside the <code>{inLoop.replace(/\[\]/g, "")}</code> loop only — <code>{loopName(inLoop)}</code> is the name the loop gives each item.{" "}
    </>
  ) : null;
  if (field.kind === "list") {
    const items = fields.filter((f) => f.path.startsWith(`${field.path}[].`) && !f.path.slice(field.path.length + 3).includes("."));
    const v = loopName(field.path);
    const cells = items.slice(0, 3).map((f) => `{{ ${expressionFor(f.path)} }}`);
    const body = cells.length ? cells.join("   ") : `{{ ${v} }}`;
    const listExpr = expressionFor(field.path);
    if (ext === "docx") {
      return {
        title: "A list: repeat a table row for each item",
        code: `{%tr for ${v} in ${listExpr} %}\n${body}\n{%tr endfor %}`,
        hint: (
          <>
            In Word: a table with a header row, then three rows — the first holds only the opening <code>{"{%tr … %}"}</code> tag, the middle one the fields
            (one per cell), the last only <code>{"{%tr endfor %}"}</code>. The middle row is repeated once per item.
          </>
        ),
      };
    }
    if (ext === "xlsx") {
      return {
        title: "A list: repeat a row for each item",
        code: `{% for ${v} in ${listExpr} %}\n${body}\n{% endfor %}`,
        hint: <>Three rows, each tag alone in column A of its row, the fields one per cell in between. Hide the two tag rows — they stay in the output as empty rows.</>,
      };
    }
    return {
      title: "A list: repeat a row for each item",
      code: `{% for ${v} in ${listExpr} %}\n  <tr><td>${cells.join("</td><td>") || `{{ ${v} }}`}</td></tr>\n{% endfor %}`,
      hint: <>Put the loop around the table row that should repeat.</>,
    };
  }
  if (field.kind === "number") {
    return {
      title: inLoop ? "A number, inside the loop" : "A number",
      code: `{{ ${expr} }}`,
      hint: (
        <>
          {loopHint}With thousands separators and two decimals: <code>{`{{ "{:,.2f}".format(${expr}) }}`}</code>
          {inLoop && (
            <>
              . A total under the table: <code>{`{{ ${expressionFor(listOf(field.path)!)} | sum(attribute="${field.path.split(".").pop()}") }}`}</code>
            </>
          )}
        </>
      ),
    };
  }
  if (field.kind === "date") {
    return {
      title: inLoop ? "A date, inside the loop" : isFilter ? "The filter the reader chose" : "A date",
      code: `{{ ${expr} }}`,
      hint: (
        <>
          {loopHint}Dates arrive as text like 2026-09-02. Day first: <code>{`{{ ${expr}[8:10] }}/{{ ${expr}[5:7] }}/{{ ${expr}[:4] }}`}</code> — month names are in
          the guide.
        </>
      ),
    };
  }
  return {
    title: isFilter ? "The filter the reader chose" : inLoop ? "A value, inside the loop" : "A value",
    code: `{{ ${expr} }}`,
    hint: (
      <>
        {loopHint}
        {isFilter ? "Filters sit beside the data, so a heading can say what was asked for. " : ""}Khmer text wraps correctly on its own — no spaces or tricks needed.
      </>
    ),
  };
}

const KIND_LABEL: Record<string, string> = { text: "text", number: "number", date: "date", boolean: "yes/no", list: "list", object: "group", empty: "empty" };

// --- the page ----------------------------------------------------------------------------------------------------------

/** #/templates/new -- a report, built the way BI tools do it: pick the data source and see what it returns, get the
 * placeholders (or a starter file with all of them placed) from those fields, design the look in Word / Excel / an
 * editor, then test it with real data and publish. The report exists as a draft from step 2 on (only people who
 * manage it see it), so #/templates/new/<id> picks up where someone left off. */
export default function NewReportWizard({ auth, reportId, navigate }: { auth: AuthInfo; reportId?: string; navigate: (route: Route, options?: { replace?: boolean }) => void }) {
  const [step, setStep] = useState<Step>(reportId ? 2 : 1);
  const [loading, setLoading] = useState(Boolean(reportId));

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  const [folderId, setFolderId] = useState<string | null>(null);

  const [source, setSource] = useState<EditableSource>({ ...EMPTY_SOURCE, type: "static" });
  const [connections, setConnections] = useState<ConnectionSummary[] | null>(null);
  const [connectionsAvailable, setConnectionsAvailable] = useState(true);
  const [params, setParams] = useState<ReportParameter[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<DataPreview | null>(null);
  const [running, setRunning] = useState(false);
  const [view, setView] = useState<"table" | "json">("table");

  const [report, setReport] = useState<ReportMeta | null>(null);
  const [fields, setFields] = useState<DataField[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [designed, setDesigned] = useState(false);
  const [check, setCheck] = useState<TemplateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [published, setPublished] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const publishedBanner = useRef<HTMLDivElement>(null);

  const orgId = auth.orgId ?? "root";

  useEffect(() => {
    api.connections
      .list()
      .then((list) => {
        setConnections(list);
        setConnectionsAvailable(true);
      })
      .catch(() => {
        setConnections([]);
        setConnectionsAvailable(false);
      });
  }, []);

  // Continuing a draft: the report, its filters, and its fields (from the sample it kept).
  useEffect(() => {
    if (!reportId || report?.report_id === reportId) return;
    setLoading(true);
    Promise.all([api.getReport(reportId), api.getDataConfig(reportId), api.wizard.check(reportId)])
      .then(([r, config, c]) => {
        setReport(r);
        setName(r.name);
        setDescription(r.description ?? "");
        setCode(r.code ?? "");
        setFolderId(r.folder_id);
        setParams(config.parameters);
        const sample = r.sample_context ?? {};
        setValues(Object.fromEntries(config.parameters.map((p) => [p.name, String(sample[p.name] ?? "")])));
        setFields(c.fields);
        setCheck(c);
        setDesigned(r.version > 1);
        setPublished(!r.is_draft);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't open this draft"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the id in the URL changes
  }, [reportId]);

  const restConnections = connections?.filter((c) => c.kind === "rest") ?? null;
  const jdbcConnections = connections?.filter((c) => c.kind === "jdbc") ?? null;
  const filterNames = params.map((p) => p.name);
  const ext: TemplateExt = report?.template_ext ?? "docx";

  // --- step 1: run the source ---------------------------------------------------------------------------------------

  function chooseKind(type: DataSourceType) {
    if (type === source.type) return;
    setSource({ ...EMPTY_SOURCE, type });
    setPreview(null);
    setParams([]);
    setValues({});
  }

  async function run() {
    setError(null);
    if (source.type === "static") {
      const parsed = parseStaticData(source.staticText);
      if (parsed.error || !parsed.value) {
        setError(parsed.error ?? "Paste the sample data first");
        return;
      }
    }
    setRunning(true);
    try {
      const result = await api.wizard.preview({ data_source: toDataSource(source), parameters: params, values });
      setParams(result.parameters);
      setValues((v) => Object.fromEntries(result.parameters.map((p) => [p.name, v[p.name] ?? ""])));
      setPreview(result);
      if (!result.missing.length) {
        setFields(result.fields);
        setView(firstTable(result.data) ? "table" : "json");
      }
    } catch (err) {
      setPreview(null);
      setError(err instanceof ApiError ? err.message : "Couldn't run the data source");
    } finally {
      setRunning(false);
    }
  }

  const ready1 = Boolean(preview && !preview.missing.length && name.trim());

  async function finishStep1() {
    if (!preview || preview.missing.length || !name.trim()) return;
    setBusy(true);
    setError(null);
    setCodeError(null);
    const sample = { ...preview.data, ...Object.fromEntries(filterNames.map((n) => [n, values[n] ?? ""])) };
    try {
      if (!report) {
        const created = await api.wizard.createDraft({
          name: name.trim(),
          description: description.trim() || null,
          code: code.trim() || null,
          folder_id: folderId,
          format: "docx",
          parameters: params,
          data_source: toDataSource(source),
          sample: preview.data,
          values,
        });
        setReport(created);
        navigate({ view: "new-report", id: created.report_id }, { replace: true });
      } else {
        // Going back and changing the data: save it to the draft, and remake the starter if it hasn't been designed yet.
        await api.putDataConfig(report.report_id, { parameters: params, data_source: toDataSource(source) });
        let updated = await api.updateReport(report.report_id, {
          name: name.trim(),
          description: description.trim(),
          folder_id: folderId,
          code: code.trim() || null,
          sample_context: sample,
        });
        if (!designed) updated = await api.wizard.starter(report.report_id, updated.template_ext);
        setReport(updated);
      }
      setFields(preview.fields);
      setStep(2);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setCodeError(err.message);
      else setError(err instanceof ApiError ? err.message : "Couldn't save the draft");
    } finally {
      setBusy(false);
    }
  }

  // --- step 2: fields and the starter ------------------------------------------------------------------------------

  const filterFields: DataField[] = params.map((p) => ({
    path: p.name,
    kind: p.type === "number" ? "number" : p.type === "date" || p.type === "datetime" ? "date" : "text",
    example: values[p.name] || null,
    count: null,
    depth: 0,
  }));
  const pickedField = [...fields, ...filterFields].find((f) => f.path === picked) ?? fields.find((f) => f.kind === "list") ?? fields[0] ?? null;
  const snippet = pickedField ? snippetFor(pickedField, fields, ext, filterNames.includes(pickedField.path)) : null;

  async function pick(field: DataField) {
    setPicked(field.path);
    const s = snippetFor(field, fields, ext, filterNames.includes(field.path));
    try {
      await navigator.clipboard.writeText(s.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  async function changeStarter(format: TemplateExt) {
    if (!report || format === report.template_ext) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.wizard.starter(report.report_id, format));
      setDesigned(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't make the starter");
    } finally {
      setBusy(false);
    }
  }

  async function downloadStarter() {
    if (!report) return;
    try {
      const { blob, filename } = await api.downloadTemplate(report.report_id);
      downloadBlob(blob, filename);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't download the template");
    }
  }

  // --- step 3: upload and check ---------------------------------------------------------------------------------------

  async function runCheck(id: string) {
    setChecking(true);
    try {
      setCheck(await api.wizard.check(id));
    } catch {
      setCheck(null);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (step === 3 && report) void runCheck(report.report_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- check on arriving at step 3
  }, [step, report?.report_id]);

  async function upload(file: File | undefined) {
    if (!file || !report) return;
    if (!/\.(docx|xlsx|html?)$/i.test(file.name)) {
      setError("Choose a .docx, .xlsx or .html template");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.replaceFile(report.report_id, file, "Designed in the New report wizard");
      setReport(updated);
      setDesigned(true);
      await runCheck(updated.report_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload the template");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    void upload(e.dataTransfer.files?.[0]);
  }

  // --- step 4: publish ------------------------------------------------------------------------------------------------

  async function publish() {
    if (!report) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.wizard.publish(report.report_id));
      setPublished(true);
      // The button is at the bottom; the confirmation (and what to do next) is at the top.
      window.requestAnimationFrame(() => publishedBanner.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't publish the report");
    } finally {
      setBusy(false);
    }
  }

  // --- navigation -----------------------------------------------------------------------------------------------------

  const reachable = (n: Step) => n === 1 || report !== null;
  function go(n: Step) {
    if (!reachable(n)) return;
    setError(null);
    setStep(n);
  }

  const next: { label: string; disabled: boolean; blocker: string; action: () => void } =
    step === 1
      ? {
          label: report ? "Save and continue" : "Next: Fields",
          disabled: busy || !ready1,
          blocker: !name.trim() ? "Give the report a name." : !preview ? "Run it first — the next step is built from what it returns." : preview.missing.length ? "Give the filters test values and run it." : "",
          action: () => void finishStep1(),
        }
      : step === 2
        ? { label: "Next: Design", disabled: false, blocker: "", action: () => go(3) }
        : step === 3
          ? { label: "Next: Preview", disabled: busy, blocker: "", action: () => go(4) }
          : { label: published ? "Published" : "Publish", disabled: busy || published, blocker: "", action: () => void publish() };

  if (loading) {
    return (
      <div className="nrw">
        <p className="muted">Opening the draft…</p>
      </div>
    );
  }

  return (
    <div className="nrw">
      <div className="page-header">
        <div>
          <h1 className="page-title">{report ? report.name : "New report"}</h1>
          <p className="page-subtitle">
            Start from your data: see exactly what it returns, design the look against those fields, then test it and publish. Already have a finished template?{" "}
            <button type="button" className="link-btn" onClick={() => navigate({ view: "gallery" })}>
              Register it directly
            </button>
            .
          </p>
        </div>
        {report && !published && <span className="badge badge-system nrw-draft-badge">Draft — only people who manage it can see it</span>}
      </div>

      <ol className="nrw-steps">
        {STEPS.map((s) => {
          const done = s.n < step || (s.n === 4 && published);
          return (
            <li key={s.n}>
              <button
                type="button"
                className={`nrw-step${s.n === step ? " active" : ""}${done ? " done" : ""}`}
                onClick={() => go(s.n)}
                disabled={!reachable(s.n)}
                aria-current={s.n === step ? "step" : undefined}
              >
                <span className="nrw-step-dot" aria-hidden="true">
                  {done ? <Check size={14} strokeWidth={3} /> : s.n}
                </span>
                <span className="nrw-step-text">
                  <span className="nrw-step-label">{s.label}</span>
                  <span className="nrw-step-sub">{s.sub}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {error && <p className="alert alert-error">{error}</p>}

      {/* ===================== 1. Data ===================== */}
      {step === 1 && (
        <section className="nrw-card">
          <div className="nrw-grid-3">
            <label>
              <span>
                Name <span className="required-mark">*</span>
              </span>
              <input type="text" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Monthly invoices" />
            </label>
            <FolderPicker value={folderId} onChange={setFolderId} hint={null} />
            <label>
              <span>
                Description <span className="muted">(optional)</span>
              </span>
              <input type="text" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
            </label>
          </div>
          {!report && (
            <ReportCodeField
              value={code}
              onChange={(v) => {
                setCode(v);
                setCodeError(null);
              }}
              suggestion={suggestCode(name)}
              serverError={codeError}
            />
          )}

          <h2 className="nrw-h2">Where does the data come from?</h2>
          <div className="nrw-kinds" role="radiogroup" aria-label="Data source">
            {KINDS.map(({ id, label, blurb, icon: Icon }) => (
              <label key={id} className={`nrw-kind${source.type === id ? " selected" : ""}`}>
                <input type="radio" name="nrw-kind" value={id} checked={source.type === id} onChange={() => chooseKind(id)} />
                <span className="nrw-kind-icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <span className="nrw-kind-text">
                  <span className="nrw-kind-label">{label}</span>
                  <span className="nrw-kind-blurb">{blurb}</span>
                </span>
              </label>
            ))}
          </div>

          <div className="nrw-source">
            <div className="nrw-source-form">
              {source.type === "static" && (
                <StaticSourceFields text={source.staticText} onChange={(text) => setSource((s) => ({ ...s, staticText: text }))} error={parseStaticData(source.staticText).error} />
              )}
              {source.type === "rest" && (
                <RequestFields
                  value={source.request}
                  onChange={(patch) => setSource((s) => ({ ...s, request: { ...s.request, ...patch } }))}
                  connections={restConnections}
                  connectionsAvailable={connectionsAvailable}
                  canManageConnections={has(auth, "connection:manage")}
                  canManageSecrets={has(auth, "secret:manage")}
                  orgId={orgId}
                  placeholders={filterNames}
                  bodyHint="Request body (JSON or text; {{ name }} works inside string values)"
                  urlExample="https://erp.example.com/api/invoices?month={{ month }}"
                />
              )}
              {source.type === "jdbc" && (
                <JdbcSourceFields
                  value={source.jdbc}
                  onChange={(patch) => setSource((s) => ({ ...s, jdbc: { ...s.jdbc, ...patch } }))}
                  connections={jdbcConnections}
                  connectionsAvailable={connectionsAvailable}
                  canManageConnections={has(auth, "connection:manage")}
                  filters={params.map((p) => ({ name: p.name, type: p.type ?? "text" }))}
                />
              )}

              {params.length > 0 && (
                <div className="nrw-filters">
                  <span className="field-label">Filters</span>
                  <p className="field-hint">
                    Found in your {source.type === "jdbc" ? "query" : "request"} — people pick them when they run the report. Give each a test value.
                  </p>
                  {params.map((p, i) => (
                    <div key={p.name} className={`nrw-filter${preview?.missing.includes(p.name) && !values[p.name] ? " missing" : ""}`}>
                      <code>{source.type === "jdbc" ? `:${p.name}` : `{{ ${p.name} }}`}</code>
                      <select
                        aria-label={`${p.name}: type`}
                        value={p.type ?? "text"}
                        onChange={(e) => setParams((list) => list.map((q, j) => (j === i ? { ...q, type: e.target.value as ParameterType } : q)))}
                      >
                        {FILTER_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      <input
                        aria-label={`${p.name}: test value`}
                        type={INPUT_TYPE[p.type ?? "text"]}
                        value={values[p.name] ?? ""}
                        onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))}
                        placeholder="test value"
                      />
                    </div>
                  ))}
                </div>
              )}

              <div className="nrw-run">
                <button type="button" className="btn btn-primary" onClick={() => void run()} disabled={running}>
                  {running ? <span className="spinner" /> : <Play size={14} aria-hidden="true" />}
                  {preview && !preview.missing.length ? "Run again" : source.type === "static" ? "Use this data" : "Run"}
                </button>
                <span className="field-hint">Runs once with the test values; nothing is saved yet.</span>
              </div>
            </div>

            <DataResult preview={preview} running={running} view={view} onView={setView} />
          </div>
        </section>
      )}

      {/* ===================== 2. Fields ===================== */}
      {step === 2 && report && (
        <section className="nrw-two">
          <div className="nrw-card">
            <h2 className="nrw-h2">Your data's fields</h2>
            <p className="field-hint">Click a field to copy the exact placeholder to type in your template. Example values come from the run.</p>
            {fields.length === 0 && filterFields.length === 0 ? (
              <p className="muted">No fields — the data was empty. Go back and run it with values that return something.</p>
            ) : (
              <ul className="nrw-fields">
                {[...fields, ...filterFields].map((f) => {
                  const isFilter = filterNames.includes(f.path) && !f.path.includes(".");
                  const selected = pickedField?.path === f.path;
                  return (
                    <li key={`${isFilter ? "filter:" : ""}${f.path}`}>
                      <button type="button" className={`nrw-field${selected ? " selected" : ""}`} onClick={() => void pick(f)} aria-pressed={selected}>
                        <code className="nrw-field-name" style={{ paddingLeft: `${Math.min(f.depth, 3) * 16}px` }}>
                          {f.path.split(/\.(?![^[]*\])/).pop()!.replace(/\[\]$/, "")}
                        </code>
                        <span className={`nrw-kind-tag kind-${isFilter ? "filter" : f.kind}`}>
                          {isFilter ? "filter" : KIND_LABEL[f.kind]}
                          {f.kind === "list" && f.count !== null ? ` · ${f.count}` : ""}
                        </span>
                        <span className="nrw-field-example">{f.example ?? ""}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="nrw-stack">
            {snippet && (
              <div className="nrw-card nrw-snippet">
                <div className="spread">
                  <h2 className="nrw-h2">{snippet.title}</h2>
                  <button type="button" className="btn btn-sm" onClick={() => pickedField && void pick(pickedField)}>
                    {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
                <pre className="nrw-code">{snippet.code}</pre>
                <p className="nrw-snippet-hint">{snippet.hint}</p>
              </div>
            )}

            <div className="nrw-card">
              <h2 className="nrw-h2">Or start from a ready-made layout</h2>
              <p className="field-hint">
                Aksor wrote a starter file with every field already placed — a line for each value, a table for each list, totals for numbers. Open it, keep the
                bracketed parts, and make it look the way you want.
              </p>
              <div className="nrw-starter">
                <div role="radiogroup" aria-label="Starter file type" className="nrw-chips">
                  {STARTER_TYPES.map((t) => (
                    <button key={t} type="button" role="radio" aria-checked={report.template_ext === t} className={`nrw-chip${report.template_ext === t ? " selected" : ""}`} onClick={() => void changeStarter(t)} disabled={busy}>
                      .{t}
                    </button>
                  ))}
                </div>
                <button type="button" className="btn" onClick={() => void downloadStarter()}>
                  <Download size={15} aria-hidden="true" />
                  Download {designed ? "current template" : "starter"} (.{report.template_ext})
                </button>
              </div>
              <p className="field-hint">
                {designed
                  ? "You've uploaded a design; choosing another file type replaces it with a new starter (your design stays in the history)."
                  : "The report already uses it, so it can be previewed right away — your design replaces it in the next step."}
              </p>
            </div>
          </div>
        </section>
      )}

      {/* ===================== 3. Design ===================== */}
      {step === 3 && report && (
        <section className="nrw-two">
          <div className="nrw-stack">
            <div className="nrw-card">
              <h2 className="nrw-h2">Upload your design</h2>
              <p className="field-hint">The file you made from the starter, or your own. It becomes the report's next version; earlier ones stay in its history.</p>
              <label
                className={`dropzone${dragging ? " dropzone-active" : ""}`}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragOver={(e) => e.preventDefault()}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
                }}
                onDrop={onDrop}
              >
                <input ref={fileInput} type="file" accept=".docx,.xlsx,.html,.htm" className="sr-only-input" onChange={(e) => void upload(e.target.files?.[0])} />
                <div className="dropzone-empty">
                  {busy ? <span className="spinner" /> : <UploadCloud size={26} strokeWidth={1.5} />}
                  <p className="dropzone-title">{busy ? "Uploading…" : "Drag & drop your template here"}</p>
                  <p className="dropzone-sub">or click to browse · docx, xlsx, html</p>
                </div>
              </label>
              <div className="nrw-current">
                <FileText size={18} aria-hidden="true" />
                <span>
                  Now using: <strong>{designed ? "your design" : "the starter"}</strong> (.{report.template_ext}, version {report.version})
                </span>
              </div>
            </div>
          </div>

          <div className="nrw-card">
            <div className="spread">
              <h2 className="nrw-h2">Checked against your data</h2>
              <button type="button" className="btn btn-sm" onClick={() => void runCheck(report.report_id)} disabled={checking}>
                {checking ? <span className="spinner" /> : null}Check again
              </button>
            </div>
            <CheckResult check={check} checking={checking} />
          </div>
        </section>
      )}

      {/* ===================== 4. Preview & publish ===================== */}
      {step === 4 && report && (
        <section className="nrw-stack">
          {published ? (
            <div className="nrw-published" role="status" ref={publishedBanner}>
              <span className="nrw-published-icon" aria-hidden="true">
                <Check size={16} strokeWidth={3} />
              </span>
              <span className="nrw-published-text">
                <strong>Published.</strong> {report.name} is in Reports — everyone with access can run it now.
              </span>
              <button type="button" className="btn" onClick={() => navigate({ view: "detail", id: report.report_id, tab: "access" })}>
                Set who can run it
              </button>
              <button type="button" className="btn btn-primary" onClick={() => navigate({ view: "run", id: report.report_id })}>
                Open in Reports
              </button>
            </div>
          ) : (
            <p className="field-hint">Run it here like a reader would — real data, the real renderer. When it looks right, publish it.</p>
          )}
          <div className="nrw-preview">
            <RunReportPage reportId={report.report_id} onBack={() => go(3)} backLabel="Design" />
          </div>
        </section>
      )}

      <div className="nrw-footer">
        <div className="nrw-footer-left">
          {step > 1 && (
            <button type="button" className="btn" onClick={() => go((step - 1) as Step)}>
              Back
            </button>
          )}
          {report && (
            <span className="field-hint">
              {published ? "Published — later changes reach readers straight away" : "Saved as a draft as you go"} —{" "}
              <button type="button" className="link-btn" onClick={() => navigate({ view: "detail", id: report.report_id })}>
                open its full settings
              </button>
              .
            </span>
          )}
        </div>
        <div className="nrw-footer-right">
          {next.blocker && <span className="nrw-blocker">{next.blocker}</span>}
          <button type="button" className="btn btn-primary" onClick={next.action} disabled={next.disabled}>
            {busy && step !== 3 ? <span className="spinner" /> : step === 4 && !published ? <Upload size={14} aria-hidden="true" /> : null}
            {next.label}
          </button>
        </div>
      </div>
    </div>
  );
}

/** The first list of rows in the data, for the table view. */
function firstTable(data: Record<string, unknown>): { key: string; rows: Record<string, unknown>[]; columns: string[] } | null {
  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value) && value.length && value.every((v) => v && typeof v === "object" && !Array.isArray(v))) {
      const rows = value as Record<string, unknown>[];
      const columns: string[] = [];
      for (const row of rows) for (const k of Object.keys(row)) if (!columns.includes(k) && (row[k] === null || typeof row[k] !== "object")) columns.push(k);
      return { key, rows, columns: columns.slice(0, 8) };
    }
  }
  return null;
}

function DataResult({ preview, running, view, onView }: { preview: DataPreview | null; running: boolean; view: "table" | "json"; onView: (v: "table" | "json") => void }) {
  const table = useMemo(() => (preview ? firstTable(preview.data) : null), [preview]);
  if (!preview || preview.missing.length) {
    return (
      <div className="nrw-result nrw-result-empty">
        {running ? (
          <span className="spinner" />
        ) : (
          <>
            <Database size={30} strokeWidth={1.5} aria-hidden="true" />
            <p>
              {preview?.missing.length
                ? `It needs a test value for ${preview.missing.join(", ")} first — fill it in on the left and run it.`
                : "Run it to see the data your report will get — that's what you design against."}
            </p>
          </>
        )}
      </div>
    );
  }
  const shown = table && view === "table" ? "table" : "json";
  return (
    <div className="nrw-result">
      <div className="nrw-result-head">
        <span className="nrw-result-status">
          <span className="badge badge-active">OK</span>
          {table ? (
            <strong>
              {table.rows.length}
              {preview.truncated ? "+" : ""} {table.key}
            </strong>
          ) : (
            <strong>{Object.keys(preview.data).length} keys</strong>
          )}
          <span className="muted">· {preview.elapsed_ms} ms</span>
        </span>
        {table && (
          <span className="nrw-tabs" role="tablist" aria-label="Result view">
            <button type="button" role="tab" aria-selected={shown === "table"} className={shown === "table" ? "active" : ""} onClick={() => onView("table")}>
              Table
            </button>
            <button type="button" role="tab" aria-selected={shown === "json"} className={shown === "json" ? "active" : ""} onClick={() => onView("json")}>
              JSON
            </button>
          </span>
        )}
      </div>
      {shown === "table" && table ? (
        <div className="nrw-result-table">
          <table className="data-table">
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.slice(0, 10).map((row, i) => (
                <tr key={i}>
                  {table.columns.map((c) => (
                    <td key={c}>{row[c] === null || row[c] === undefined ? "" : String(row[c])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {(table.rows.length > 10 || preview.truncated) && (
            <p className="field-hint nrw-result-more">
              Showing {Math.min(10, table.rows.length)} rows{preview.truncated ? " — the report keeps the first 20 as its sample; a real run gets them all" : ""}.
            </p>
          )}
        </div>
      ) : (
        <pre className="nrw-json">{JSON.stringify(preview.data, null, 2)}</pre>
      )}
    </div>
  );
}

function CheckResult({ check, checking }: { check: TemplateCheck | null; checking: boolean }) {
  if (!check) return <p className="muted">{checking ? "Checking…" : "Upload a template to compare it with your data."}</p>;
  if (!check.checked) return <p className="alert alert-error">{check.reason}</p>;
  return (
    <ul className="nrw-checks">
      <li className="ok">
        <Check size={14} strokeWidth={3} aria-hidden="true" />
        <span>
          <strong>
            {check.matched.length} placeholder{check.matched.length === 1 ? "" : "s"}
          </strong>{" "}
          match your data.
        </span>
      </li>
      {check.unknown.map((u) => (
        <li key={u.placeholder} className="warn">
          <TriangleAlert size={14} aria-hidden="true" />
          <span>
            <code>{`{{ ${u.placeholder} }}`}</code> isn't in your data, so it would print nothing.
            {u.suggestion && (
              <>
                {" "}
                Did you mean <code>{u.suggestion}</code>?
              </>
            )}
          </span>
        </li>
      ))}
      {check.unknown.length === 0 && (
        <li className="ok">
          <Check size={14} strokeWidth={3} aria-hidden="true" />
          <span>No unknown placeholders.</span>
        </li>
      )}
      {check.unused.length > 0 && (
        <li className="info">
          <span className="nrw-info-dot" aria-hidden="true">
            i
          </span>
          <span>
            Not used: {check.unused.map((u, i) => (
              <span key={u}>
                {i > 0 && ", "}
                <code>{u.replace(/\[\]/g, "")}</code>
              </span>
            ))}
            . Fine if that's on purpose.
          </span>
        </li>
      )}
    </ul>
  );
}
