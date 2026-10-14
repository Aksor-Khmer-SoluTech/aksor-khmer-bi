import { useEffect, useMemo, useRef, useState } from "react";
import { BellRing, ChartColumnBig, ChartLine, Download, FolderOpen, LayoutDashboard, Lock, Save, Table2, Trash2, X } from "lucide-react";
import { api, ApiError } from "../api";
import { has } from "../admin/sections";
import { initialValue } from "../dateFormat";
import { downloadBlob } from "../download";
import type { Route } from "../hooks";
import type { AnalysisChart, AnalysisView, AnalyzeDataset, AnalyzeForm, AuthInfo, DateBucket, PivotLayout, PivotResult, PivotValue } from "../types";
import { ParameterField } from "./RunReportPage";
import { AddToDashboard, AlertMe } from "./AnalyzeActions";

/** Analyze (api/app/analyze.py): pick a dataset, set its filters (narrowed to your access), put fields in rows and
 * columns and measures in values -- a pivot table or a chart -- then export it or keep the view. The server fetches
 * the data once per filter set and re-pivots it for every change, so moving a field answers at once. */

const COUNT = "__rows";
const SERIES = ["var(--color-accent)", "#e07a1f", "#18794a", "#9b3fb4", "#c23b4a", "#0f8a8a"];
const EMPTY: PivotLayout = { rows: [], columns: [], values: [], buckets: {} };
const keyText = (k: (string | number | null)[]) => k.map((v) => (v === null ? "(blank)" : String(v))).join(" · ") || "All";
const isKhmer = (s: string) => /[ក-៿]/.test(s);

export function Chart({ result, kind }: { result: PivotResult; kind: "bar" | "line" }) {
  const hasColumns = result.labels.columns.length > 0;
  const series = hasColumns ? result.column_keys.map(keyText) : [result.labels.values[0]?.label ?? ""];
  const cats = result.row_keys.map(keyText);
  const data = series.map((_, si) => cats.map((_, ci) => (result.cells[ci][hasColumns ? si : 0]?.[0]?.v ?? 0) || 0));
  const max = Math.max(1, ...data.flat());
  // The axis' top: 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8 or 10 x a power of ten -- the same as the exported chart.
  const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
  const top = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((s) => s * magnitude).find((t) => t >= max) ?? max;
  // Labels side by side need room; with many categories they tilt instead of running into each other.
  const tilt = cats.length > 5 && (800 - 100) / Math.max(1, cats.length) < 90;
  const W = 800, H = tilt ? 360 : 320, L = 84, R = 16, T = 12, B = tilt ? 96 : 44;
  const iw = W - L - R, ih = H - T - B;
  const y = (v: number) => T + ih - (v / top) * ih;
  const band = iw / Math.max(1, cats.length);
  const short = (v: number) => (top >= 1e7 ? `${+(v / 1e6).toFixed(1)}M` : top >= 1e4 ? `${+(v / 1e3).toFixed(1)}K` : v.toLocaleString());
  const text = result.labels.values[0];
  if (cats.length === 0) return <p className="muted p-4">No rows for these filters.</p>;
  return (
    <div className="grid gap-2 p-3.5">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${text?.label ?? ""} chart`} className="h-auto w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(f * top)} y2={y(f * top)} stroke="var(--color-border-soft)" />
            <text x={L - 8} y={y(f * top) + 4} textAnchor="end" className="fill-text-faint text-[11px]">
              {short(f * top)}
            </text>
          </g>
        ))}
        {kind === "bar"
          ? cats.map((c, ci) =>
              series.map((s, si) => {
                const w = Math.min(44, (band * 0.78) / series.length);
                const x = L + ci * band + (band - w * series.length) / 2 + si * w;
                const v = data[si][ci];
                return (
                  <rect key={`${ci}-${si}`} x={x} y={y(v)} width={Math.max(w - 3, 1)} height={T + ih - y(v)} rx={3} fill={SERIES[si % SERIES.length]}>
                    <title>{`${c} · ${s}: ${result.cells[ci][hasColumns ? si : 0]?.[0]?.t ?? "—"}`}</title>
                  </rect>
                );
              }),
            )
          : series.map((s, si) => (
              <g key={s}>
                <polyline fill="none" stroke={SERIES[si % SERIES.length]} strokeWidth={2.5} points={cats.map((_, ci) => `${L + ci * band + band / 2},${y(data[si][ci])}`).join(" ")} />
                {cats.map((c, ci) => (
                  <circle key={ci} cx={L + ci * band + band / 2} cy={y(data[si][ci])} r={4} fill={SERIES[si % SERIES.length]}>
                    <title>{`${c} · ${s}: ${result.cells[ci][hasColumns ? si : 0]?.[0]?.t ?? "—"}`}</title>
                  </circle>
                ))}
              </g>
            ))}
        {cats.map((c, ci) => {
          const x = L + ci * band + band / 2;
          const text = c.length > 22 ? `${c.slice(0, 21)}…` : c;
          return tilt ? (
            <text key={ci} x={x} y={H - B + 14} textAnchor="end" transform={`rotate(-35 ${x} ${H - B + 14})`} className="fill-text-dim text-[12px]" style={isKhmer(c) ? { fontFamily: "Khmer OS Siemreap" } : undefined}>
              {text}
            </text>
          ) : (
            <text key={ci} x={x} y={H - B + 20} textAnchor="middle" className="fill-text-dim text-[11px]" style={isKhmer(c) ? { fontFamily: "Khmer OS Siemreap" } : undefined}>
              {text}
            </text>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-[0.8rem] text-text-dim">
        {series.map((s, si) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[si % SERIES.length] }} />
            {s}
          </span>
        ))}
        {result.labels.values.length > 1 && <span className="text-text-faint">Charting {text?.label}; the table shows every value.</span>}
      </div>
    </div>
  );
}

export function PivotTable({ result }: { result: PivotResult }) {
  const { labels } = result;
  const values = labels.values;
  const hasColumns = labels.columns.length > 0;
  const cell = (entries: PivotValue[] | null | undefined) =>
    values.map((_, i) => {
      const e = entries?.[i];
      return (
        <td key={i} className={e && e.v !== null ? "" : "text-text-faint"}>
          {e && e.v !== null ? e.t : "—"}
        </td>
      );
    });
  const name = (l: { label: string; label_km: string | null }) => l.label_km || l.label;
  return (
    <div className="overflow-x-auto">
      <table className="data-table static-rows analyze-table">
        <thead>
          {hasColumns && (
            <tr>
              <th colSpan={Math.max(1, labels.rows.length)}>{labels.columns.map(name).join(" · ")}</th>
              {result.column_keys.map((ck, i) => (
                <th key={i} colSpan={values.length} className="text-center">
                  {keyText(ck)}
                </th>
              ))}
              <th colSpan={values.length} className="text-center">
                Total
              </th>
            </tr>
          )}
          <tr>
            {(labels.rows.length ? labels.rows : [{ label: "", label_km: null }]).map((r, i) => (
              <th key={i}>{name(r)}</th>
            ))}
            {[...(hasColumns ? result.column_keys : [[]]), ...(hasColumns ? [["total"]] : [])].flatMap((_, ci) =>
              values.map((v) => (
                <th key={`${ci}-${v.key}`} className="text-right">
                  {name(v)}
                </th>
              )),
            )}
          </tr>
        </thead>
        <tbody>
          {result.row_keys.map((rk, ri) => (
            <tr key={ri}>
              {(rk.length ? rk : ["All"]).map((v, i) => (
                <td key={i} className="text-left" lang={typeof v === "string" && isKhmer(v) ? "km" : undefined}>
                  {v === null ? "(blank)" : String(v)}
                </td>
              ))}
              {hasColumns ? [...result.cells[ri].map((c) => cell(c)), cell(result.row_totals[ri])] : cell(result.cells[ri][0])}
            </tr>
          ))}
          <tr className="analyze-total">
            <td colSpan={Math.max(1, labels.rows.length)} className="text-left">
              Total
            </td>
            {hasColumns && result.column_totals.map((ct) => cell(ct))}
            {cell(result.total)}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function AnalyzePage({ auth, viewId, navigate }: { auth: AuthInfo; viewId?: string; navigate: (r: Route) => void }) {
  const [datasets, setDatasets] = useState<AnalyzeDataset[] | null>(null);
  const [views, setViews] = useState<AnalysisView[]>([]);
  const [dataset, setDataset] = useState("");
  const [form, setForm] = useState<AnalyzeForm | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [layout, setLayout] = useState<PivotLayout>(EMPTY);
  const [chart, setChart] = useState<AnalysisChart>("table");
  const [result, setResult] = useState<PivotResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<AnalysisView | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const pending = useRef<AnalysisView | null>(null);
  const [panel, setPanel] = useState<"dashboard" | "alert" | null>(null);

  useEffect(() => {
    api.analyze.datasets().then(setDatasets).catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the datasets"));
    api.analyze.views.list().then(setViews).catch(() => setViews([]));
  }, []);

  // A saved view in the URL (#/analyze/<id>): open it.
  useEffect(() => {
    if (!viewId) return;
    api.analyze.views
      .get(viewId)
      .then((v) => {
        pending.current = v;
        setCurrent(v);
        setTitle(v.title);
        setChart(v.config.view);
        setDataset(v.dataset);
      })
      .catch(() => setError("That saved view doesn't exist, or isn't yours"));
  }, [viewId]);

  // First dataset by default.
  useEffect(() => {
    if (!dataset && !viewId && datasets?.length) setDataset(datasets[0].name);
  }, [datasets, dataset, viewId]);

  // A dataset chosen: its filters, fields and measures -- and a first layout (or the saved view's).
  useEffect(() => {
    if (!dataset) return;
    setForm(null);
    setResult(null);
    api.analyze
      .form(dataset)
      .then((f) => {
        setForm(f);
        const saved = pending.current?.dataset === dataset ? pending.current : null;
        pending.current = null;
        const defaults: Record<string, string> = {};
        for (const p of f.parameters) defaults[p.name] = p.options?.length ? p.options[0].value : initialValue(p.type, p.default_value);
        setValues({ ...defaults, ...(saved?.config.values ?? {}) });
        if (saved) setLayout(saved.config.layout);
        else {
          const firstText = f.fields.find((x) => x.type === "text");
          setLayout({ ...EMPTY, rows: firstText ? [firstText.name] : [], values: [f.measures[0]?.key ?? COUNT] });
        }
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't open the dataset"));
  }, [dataset]);

  // Re-pivot on every change (debounced); the server keeps the fetched data, so this is cheap.
  useEffect(() => {
    if (!form || !layout.values.length) return;
    if (form.parameters.some((p) => p.required && !(values[p.name] ?? "").trim())) return;
    const timer = window.setTimeout(() => {
      setRunning(true);
      api.analyze
        .pivot(form.dataset, values, layout)
        .then((r) => {
          setResult(r);
          setError(null);
        })
        .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't work it out"))
        .finally(() => setRunning(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [form, values, layout]);

  const fieldLabel = (name: string) => {
    const f = form?.fields.find((x) => x.name === name);
    return f?.label || name;
  };
  const measureOptions = useMemo(
    () => [...(form?.measures ?? []).map((m) => ({ key: m.key, label: m.label, km: m.label_km })), { key: COUNT, label: "Rows (count)", km: "ចំនួនជួរ" }],
    [form],
  );

  function place(where: "rows" | "columns", name: string) {
    setLayout((prev) => {
      const there = prev[where].includes(name);
      const other = where === "rows" ? "columns" : "rows";
      return { ...prev, [where]: there ? prev[where].filter((n) => n !== name) : [...prev[where], name].slice(0, 3), [other]: prev[other].filter((n) => n !== name) };
    });
  }
  const toggleValue = (key: string) =>
    setLayout((prev) => ({ ...prev, values: prev.values.includes(key) ? prev.values.filter((k) => k !== key) : [...prev.values, key].slice(0, 6) }));

  async function exportAs(format: "pdf" | "docx" | "xlsx") {
    if (!form) return;
    setBusy(format);
    try {
      const { blob, filename } = await api.analyze.export({ dataset: form.dataset, values, layout, format, chart, title: title.trim() || undefined });
      downloadBlob(blob, filename);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  async function save(asNew: boolean) {
    if (!form || !title.trim()) return;
    setBusy("save");
    try {
      const body = { title: title.trim(), dataset: form.dataset, config: { values, layout, view: chart } };
      const saved = current && !asNew ? await api.analyze.views.update(current.id, body) : await api.analyze.views.create(body);
      setCurrent(saved);
      setViews((prev) => [saved, ...prev.filter((v) => v.id !== saved.id)]);
      setNotice(`Saved “${saved.title}”`);
      navigate({ view: "analyze", id: saved.id });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the view");
    } finally {
      setBusy(null);
    }
  }

  async function removeView(v: AnalysisView) {
    await api.analyze.views.delete(v.id).catch(() => {});
    setViews((prev) => prev.filter((x) => x.id !== v.id));
    if (current?.id === v.id) {
      setCurrent(null);
      navigate({ view: "analyze" });
    }
  }

  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 2600);
    return () => window.clearTimeout(t);
  }, [notice]);

  if (datasets !== null && datasets.length === 0) {
    return (
      <div className="empty-state">
        <ChartColumnBig size={30} strokeWidth={1.4} aria-hidden="true" />
        <p>No dataset to analyze yet.</p>
        <p className="muted">
          Analyze works on datasets — a source with its fields and measures.{" "}
          {has(auth, "dataset:manage") ? <a href="#/admin/datasets">Make one under Manage → Datasets</a> : "Ask someone who manages datasets to make one, or to let you use it"}.
        </p>
      </div>
    );
  }

  const chosen = datasets?.find((d) => d.name === dataset);
  return (
    <div className="grid gap-4">
      <div className="page-header">
        <div>
          <h1 className="page-title">{current ? current.title : "Analyze"}</h1>
          <p className="page-subtitle">Put fields in rows and columns and measures in values — as a table or a chart — then export it or keep the view.</p>
        </div>
        <div className="page-header-actions flex-wrap">
          <button type="button" className="btn" onClick={() => exportAs("xlsx")} disabled={!result || busy !== null}>
            {busy === "xlsx" ? <span className="spinner" /> : <Download size={14} aria-hidden="true" />} Excel
          </button>
          <button type="button" className="btn" onClick={() => exportAs("docx")} disabled={!result || busy !== null}>
            {busy === "docx" ? <span className="spinner" /> : <Download size={14} aria-hidden="true" />} Word
          </button>
          <button type="button" className="btn btn-primary" onClick={() => exportAs("pdf")} disabled={!result || busy !== null}>
            {busy === "pdf" ? <span className="spinner" /> : <Download size={14} aria-hidden="true" />} Export PDF
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-[12px] border border-border-soft bg-bg-raised p-3">
        <label className="mb-0 min-w-[14rem]">
          <span>Dataset</span>
          <select
            value={dataset}
            onChange={(e) => {
              setCurrent(null);
              setDataset(e.target.value);
              if (viewId) navigate({ view: "analyze" });
            }}
          >
            {datasets?.map((d) => (
              <option key={d.name} value={d.name}>
                {d.title}
              </option>
            ))}
          </select>
        </label>
        {form?.parameters.map((p) => (
          <div key={p.name} className="analyze-filter mb-0 min-w-[11rem]">
            <ParameterField parameter={p} value={values[p.name] ?? ""} onChange={(next) => setValues((prev) => ({ ...prev, [p.name]: next }))} />
          </div>
        ))}
        <span className="flex-1" />
        {chosen?.access_mode === "restricted" && (
          <span className="inline-flex items-center gap-1 rounded-full bg-highlight-soft px-2.5 py-1 text-[0.75rem] font-medium text-highlight-strong" title="Restricted: only the values you're allowed">
            <Lock size={12} aria-hidden="true" /> Restricted to your values
          </span>
        )}
      </div>

      {error && <p className="alert alert-error m-0">{error}</p>}
      {notice && <p className="alert alert-success m-0">{notice}</p>}

      <div className="grid items-start gap-3.5 md:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="grid gap-3 rounded-[12px] border border-border-soft bg-bg-raised p-3" aria-label="Fields and measures">
          <div>
            <h3 className="docs-home-label">Fields</h3>
            {form?.fields.length === 0 && <p className="field-hint">This dataset has no fields yet — run it on its Fields tab first.</p>}
            {form?.fields.map((f) => (
              <div key={`${f.source}.${f.name}`} className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-bg-panel">
                <span className="mono w-7 rounded bg-bg-panel py-0.5 text-center text-[0.62rem] text-text-dim">{f.type === "date" || f.type === "datetime" ? "DT" : f.type === "text" ? "Aa" : "#"}</span>
                <span className="min-w-0 flex-1 leading-tight">
                  {f.label || f.name}
                  {f.label_km && <small className="block text-[0.72rem] text-text-faint">{f.label_km}</small>}
                </span>
                <button type="button" className={`analyze-chip${layout.rows.includes(f.name) ? " on" : ""}`} onClick={() => place("rows", f.name)} aria-label={`${f.label || f.name} in rows`} aria-pressed={layout.rows.includes(f.name)}>
                  R
                </button>
                <button type="button" className={`analyze-chip${layout.columns.includes(f.name) ? " on" : ""}`} onClick={() => place("columns", f.name)} aria-label={`${f.label || f.name} in columns`} aria-pressed={layout.columns.includes(f.name)}>
                  C
                </button>
              </div>
            ))}
          </div>
          <div>
            <h3 className="docs-home-label">Values</h3>
            {measureOptions.map((m) => (
              <label key={m.key} className="checkbox-label mb-0 rounded-md px-1.5 py-1 hover:bg-bg-panel">
                <input type="checkbox" checked={layout.values.includes(m.key)} onChange={() => toggleValue(m.key)} />
                <span className="leading-tight">
                  {m.label}
                  {m.km && <small className="block text-[0.72rem] text-text-faint">{m.km}</small>}
                </span>
              </label>
            ))}
          </div>
          <div>
            <h3 className="docs-home-label">Saved views</h3>
            {views.length === 0 ? (
              <p className="field-hint m-0">None yet — name this one below and save it.</p>
            ) : (
              views.map((v) => (
                <div key={v.id} className={`flex items-center gap-1 rounded-md px-1.5 py-1 ${current?.id === v.id ? "bg-accent-soft" : "hover:bg-bg-panel"}`}>
                  <button type="button" className="link-btn min-w-0 flex-1 truncate text-left" onClick={() => navigate({ view: "analyze", id: v.id })}>
                    <FolderOpen size={13} className="mr-1 inline" aria-hidden="true" />
                    {v.title}
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm icon-only" aria-label={`Delete ${v.title}`} onClick={() => removeView(v)}>
                    <Trash2 size={13} />
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>

        <section className="grid min-w-0 gap-3">
          <div className="grid gap-2.5 sm:grid-cols-2">
            {(["rows", "columns"] as const).map((where) => (
              <div key={where} className="min-h-[64px] rounded-[12px] border border-dashed border-border bg-bg-raised p-2.5">
                <h4 className="docs-home-label mb-1.5">{where === "rows" ? "Rows" : "Columns"}</h4>
                <div className="flex flex-wrap gap-1.5">
                  {layout[where].length === 0 && <span className="text-[0.8rem] text-text-faint">{where === "rows" ? "Add a field with R" : "Optional — add one with C"}</span>}
                  {layout[where].map((name) => {
                    const f = form?.fields.find((x) => x.name === name);
                    const isDate = f?.type === "date" || f?.type === "datetime";
                    return (
                      <span key={name} className="inline-flex items-center gap-1 rounded-full bg-accent-soft py-1 pr-1 pl-2.5 text-[0.8rem] font-medium text-accent-strong">
                        {fieldLabel(name)}
                        {isDate && (
                          <select
                            className="analyze-bucket"
                            aria-label={`Group ${fieldLabel(name)} by`}
                            value={layout.buckets[name] ?? ""}
                            onChange={(e) =>
                              setLayout((prev) => {
                                const buckets = { ...prev.buckets };
                                if (e.target.value) buckets[name] = e.target.value as DateBucket;
                                else delete buckets[name];
                                return { ...prev, buckets };
                              })
                            }
                          >
                            <option value="">each value</option>
                            <option value="day">by day</option>
                            <option value="month">by month</option>
                            <option value="year">by year</option>
                          </select>
                        )}
                        <button type="button" className="border-0 bg-transparent px-1 text-inherit opacity-70 hover:opacity-100" aria-label={`Remove ${fieldLabel(name)}`} onClick={() => place(where, name)}>
                          <X size={13} />
                        </button>
                      </span>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-[12px] border border-border-soft bg-bg-raised">
            <div className="flex flex-wrap items-center gap-2.5 border-b border-border-soft px-3 py-2">
              <div className="segmented segmented-sm" role="radiogroup" aria-label="Show as">
                {(
                  [
                    ["table", "Table", Table2],
                    ["bar", "Bar", ChartColumnBig],
                    ["line", "Line", ChartLine],
                  ] as const
                ).map(([id, label, Icon]) => (
                  <button key={id} type="button" role="radio" aria-checked={chart === id} className={chart === id ? "segmented-btn active gap-1.5" : "segmented-btn gap-1.5"} onClick={() => setChart(id)}>
                    <Icon size={14} aria-hidden="true" /> {label}
                  </button>
                ))}
              </div>
              <span className="flex-1" />
              {running && <span className="spinner" aria-label="Working it out" />}
              {result && (
                <span className="mono text-[0.75rem] text-text-faint">
                  {result.row_count.toLocaleString()} rows · {result.row_keys.length}×{Math.max(1, result.column_keys.length)} · {result.elapsed_ms} ms
                </span>
              )}
            </div>
            {!result && !error && <p className="muted p-4">{form ? "Working it out…" : "Choose a dataset."}</p>}
            {result && (chart === "table" ? <PivotTable result={result} /> : <Chart result={result} kind={chart} />)}
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <label className="mb-0 min-w-[16rem] flex-1">
              <span>Name this view</span>
              <input type="text" maxLength={120} value={title} placeholder="Sales by branch and month" onChange={(e) => setTitle(e.target.value)} />
            </label>
            <button type="button" className="btn" onClick={() => save(false)} disabled={!result || !title.trim() || busy !== null || !auth.username}>
              {busy === "save" ? <span className="spinner" /> : <Save size={14} aria-hidden="true" />} {current ? "Save changes" : "Save view"}
            </button>
            {current && (
              <button type="button" className="btn" onClick={() => save(true)} disabled={!result || !title.trim() || busy !== null}>
                Save as new
              </button>
            )}
          </div>
          <p className="field-hint m-0">Your saved views are yours alone. The title is also the heading of an exported file.</p>

          <div className="flex flex-wrap gap-2">
            <button type="button" className={`btn btn-sm${panel === "dashboard" ? " btn-primary" : ""}`} onClick={() => setPanel(panel === "dashboard" ? null : "dashboard")} disabled={!result}>
              <LayoutDashboard size={14} aria-hidden="true" /> Add to dashboard
            </button>
            {has(auth, "job:manage") && (
              <button type="button" className={`btn btn-sm${panel === "alert" ? " btn-primary" : ""}`} onClick={() => setPanel(panel === "alert" ? null : "alert")} disabled={!form}>
                <BellRing size={14} aria-hidden="true" /> Alert me
              </button>
            )}
          </div>
          {panel === "dashboard" && form && (
            <AddToDashboard
              form={form}
              values={values}
              layout={layout}
              chart={chart}
              title={title}
              onDone={(message, dashboardId) => {
                setPanel(null);
                setNotice(message);
                window.setTimeout(() => navigate({ view: "dashboards", id: dashboardId }), 900);
              }}
            />
          )}
          {panel === "alert" && form && (
            <AlertMe
              form={form}
              values={values}
              orgId={auth.orgId ?? "root"}
              onDone={(message) => {
                setPanel(null);
                setNotice(message);
              }}
            />
          )}
        </section>
      </div>
    </div>
  );
}
