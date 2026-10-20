import { useEffect, useMemo, useRef, useState } from "react";
import { BellRing, ChartColumnBig, ChartLine, Download, FolderOpen, LayoutDashboard, Lock, Save, Table2, Trash2, X } from "lucide-react";
import { api, ApiError } from "../api";
import { has } from "../admin/sections";
import { initialValue } from "../dateFormat";
import { downloadBlob } from "../download";
import type { Route } from "../hooks";
import type { AnalysisChart, AnalysisView, AnalyzeDataset, AnalyzeForm, AuthInfo, DateBucket, PivotLayout, PivotResult, PivotValue, ShowAsMode } from "../types";
import { ParameterField } from "./RunReportPage";
import { AddToDashboard, AlertMe } from "./AnalyzeActions";
import { reportError } from "../notify";

/** Analyze (api/app/analyze.py): pick a dataset, set its filters (narrowed to your access), put fields in rows and
 * columns and measures in values -- a pivot table or a chart -- then export it or keep the view. The server fetches
 * the data once per filter set and re-pivots it for every change, so moving a field answers at once. */

const COUNT = "__rows";
const SERIES = ["var(--color-accent)", "#e07a1f", "#18794a", "#9b3fb4", "#c23b4a", "#0f8a8a"];
const EMPTY: PivotLayout = { rows: [], columns: [], values: [], buckets: {} };
const keyText = (k: (string | number | null)[]) => k.map((v) => (v === null ? "(blank)" : String(v))).join(" · ") || "All";
const isKhmer = (s: string) => /[ក-៿]/.test(s);
const SHOW_AS: [ShowAsMode | "", string][] = [
  ["", "as is"],
  ["percent_of_total", "% of total"],
  ["percent_of_row", "% of row total"],
  ["percent_of_column", "% of column total"],
  ["running_total", "running total"],
  ["difference", "change from previous"],
  ["percent_difference", "% change from previous"],
];
const SEQUENCE: ShowAsMode[] = ["running_total", "difference", "percent_difference"];

/** The layout as sent: statistics that no longer fit the arrangement are left out rather than refused -- a trend
 * needs exactly one row field; a running total or change runs along a side that has a field; a value no longer shown
 * keeps no "show as". */
export function sendable(layout: PivotLayout): PivotLayout {
  const showAs: NonNullable<PivotLayout["show_as"]> = {};
  for (const [key, spec] of Object.entries(layout.show_as ?? {})) {
    if (!layout.values.includes(key)) continue;
    if (!SEQUENCE.includes(spec.mode)) showAs[key] = spec;
    else if (layout[spec.along].length) showAs[key] = spec;
    else if (layout.rows.length || layout.columns.length) showAs[key] = { ...spec, along: layout.rows.length ? "rows" : "columns" };
  }
  const placed = [...layout.rows, ...layout.columns];
  const trend = layout.trend && layout.rows.length === 1 ? { ...layout.trend, value: layout.trend.value && layout.values.includes(layout.trend.value) ? layout.trend.value : null } : null;
  return {
    ...layout,
    ranges: Object.fromEntries(Object.entries(layout.ranges ?? {}).filter(([name]) => placed.includes(name))),
    show_as: showAs,
    trend,
    outliers: layout.outliers ?? null,
  };
}

const STEPS = [1, 2, 2.5, 3, 4, 5, 6, 8, 10];
const TREND_GREY = "var(--color-text-faint)";

/** About four round steps from at or below `low` (zero, or less when a change or a trend goes negative) to at or
 * above `high` -- the same as the exported chart (analyze_export.axis_range). */
function axisRange(low: number, high: number) {
  const raw = (high - low) / 4;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = STEPS.map((n) => n * magnitude).find((t) => t >= raw * (1 - 1e-9)) ?? raw;
  const bottom = Math.floor(low / step + 1e-9) * step;
  const top = Math.ceil(high / step - 1e-9) * step;
  const ticks = Array.from({ length: Math.round((top - bottom) / step) + 1 }, (_, n) => bottom + n * step);
  return { bottom, top, ticks };
}

/** Which value a chart draws: the one a trend follows, else the first. */
export const chartedIndex = (result: PivotResult) => (result.trend ? Math.max(0, result.layout.values.indexOf(result.trend.value)) : 0);

export function Chart({ result, kind }: { result: PivotResult; kind: "bar" | "line" }) {
  const vi = chartedIndex(result);
  const hasColumns = result.labels.columns.length > 0;
  const series = hasColumns ? result.column_keys.map(keyText) : [result.labels.values[vi]?.label ?? ""];
  const trend = result.trend;
  const ahead = trend?.forecast_keys ?? [];
  const known = result.row_keys.length;
  const cats = [...result.row_keys.map(keyText), ...ahead];
  const entry = (ci: number, si: number) => result.cells[ci][hasColumns ? si : 0]?.[vi];
  const data = series.map((_, si) => result.row_keys.map((_, ci) => entry(ci, si)?.v ?? 0));
  // Trend lines (dashed, carried into the forecast) and moving averages, drawn over the marks.
  const overlays = (trend?.series ?? []).flatMap((line, si) => {
    const out: { points: [number, number][]; color: string; dashed: boolean; name: string; si: number }[] = [];
    if (line.fitted) {
      const all = [...line.fitted, ...(line.forecast ?? []).map((f) => f.v)];
      out.push({ points: all.flatMap((v, ci) => (v === null ? [] : [[ci, v] as [number, number]])), color: SERIES[si % SERIES.length], dashed: true, name: `${series[si]} trend`, si });
    }
    if (line.moving_average) {
      out.push({ points: line.moving_average.flatMap((v, ci) => (v === null ? [] : [[ci, v] as [number, number]])), color: TREND_GREY, dashed: false, name: `${series[si]} moving average`, si });
    }
    return out;
  });
  const everything = [...data.flat(), ...overlays.flatMap((o) => o.points.map((p) => p[1]))];
  const low = Math.min(0, ...everything);
  const high = Math.max(0, ...everything);
  const { bottom, top, ticks } = axisRange(low, high > low ? high : low + 1);
  const percent = (result.formats?.[result.layout.values[vi]] ?? "").includes("%");
  // Labels side by side need room; with many categories they tilt instead of running into each other.
  const tilt = cats.length > 5 && (800 - 100) / Math.max(1, cats.length) < 90;
  const W = 800, H = tilt ? 360 : 320, L = 84, R = 16, T = 12, B = tilt ? 96 : 44;
  const iw = W - L - R, ih = H - T - B;
  const y = (v: number) => T + ih - ((v - bottom) / (top - bottom)) * ih;
  const band = iw / Math.max(1, cats.length);
  const span = Math.max(top, -bottom);
  const short = (v: number) =>
    percent
      ? `${+(v * 100).toFixed(1)}%`
      : span >= 1e7
        ? `${+(v / 1e6).toFixed(1)}M`
        : span >= 1e4
          ? `${+(v / 1e3).toFixed(1)}K`
          : (+v.toFixed(2)).toLocaleString();
  const text = result.labels.values[vi];
  if (known === 0) return <p className="muted p-4">No rows for these filters.</p>;
  return (
    <div className="grid gap-2 p-3.5">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${text?.label ?? ""} chart`} className="h-auto w-full">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v === 0 && bottom < 0 ? "var(--color-text-faint)" : "var(--color-border-soft)"} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" className="fill-text-faint text-[11px]">
              {short(v)}
            </text>
          </g>
        ))}
        {ahead.length > 0 && <rect x={L + known * band} y={T} width={ahead.length * band} height={ih} fill="var(--color-bg-panel)" opacity={0.6} />}
        {kind === "bar"
          ? result.row_keys.map((_, ci) =>
              series.map((s, si) => {
                const w = Math.min(44, (band * 0.78) / series.length);
                const x = L + ci * band + (band - w * series.length) / 2 + si * w;
                const v = data[si][ci];
                const e = entry(ci, si);
                return (
                  <rect key={`${ci}-${si}`} x={x} y={Math.min(y(v), y(0))} width={Math.max(w - 3, 1)} height={Math.abs(y(0) - y(v))} rx={3} fill={SERIES[si % SERIES.length]} stroke={e?.o ? "var(--color-highlight)" : undefined} strokeWidth={e?.o ? 3 : undefined}>
                    <title>{`${cats[ci]} · ${s}: ${e?.t ?? "—"}${e?.o ? ` (outlier, ${e.o})` : ""}`}</title>
                  </rect>
                );
              }),
            )
          : series.map((s, si) => (
              <g key={s}>
                <polyline fill="none" stroke={SERIES[si % SERIES.length]} strokeWidth={2.5} points={result.row_keys.map((_, ci) => `${L + ci * band + band / 2},${y(data[si][ci])}`).join(" ")} />
                {result.row_keys.map((_, ci) => {
                  const e = entry(ci, si);
                  return (
                    <circle key={ci} cx={L + ci * band + band / 2} cy={y(data[si][ci])} r={e?.o ? 6 : 4} fill={SERIES[si % SERIES.length]} stroke={e?.o ? "var(--color-highlight)" : undefined} strokeWidth={e?.o ? 3 : undefined}>
                      <title>{`${cats[ci]} · ${s}: ${e?.t ?? "—"}${e?.o ? ` (outlier, ${e.o})` : ""}`}</title>
                    </circle>
                  );
                })}
              </g>
            ))}
        {overlays.map((o, oi) => (
          <g key={oi}>
            <polyline fill="none" stroke={o.color} strokeWidth={1.8} strokeDasharray={o.dashed ? "6 4" : undefined} opacity={0.9} points={o.points.map(([ci, v]) => `${L + ci * band + band / 2},${y(v)}`).join(" ")}>
              <title>{o.name}</title>
            </polyline>
            {o.points
              .filter(([ci]) => ci >= known)
              .map(([ci, v]) => (
                <circle key={ci} cx={L + ci * band + band / 2} cy={y(v)} r={4} fill="var(--color-bg-raised)" stroke={o.color} strokeWidth={1.8}>
                  <title>{`${cats[ci]} · ${series[o.si]}: forecast ${trend?.series[o.si]?.forecast?.[ci - known]?.t ?? ""}`}</title>
                </circle>
              ))}
          </g>
        ))}
        {cats.map((c, ci) => {
          const x = L + ci * band + band / 2;
          const label = c.length > 22 ? `${c.slice(0, 21)}…` : c;
          const cls = ci >= known ? "fill-text-faint italic" : "fill-text-dim";
          return tilt ? (
            <text key={ci} x={x} y={H - B + 14} textAnchor="end" transform={`rotate(-35 ${x} ${H - B + 14})`} className={`${cls} text-[12px]`} style={isKhmer(c) ? { fontFamily: "Khmer OS Siemreap" } : undefined}>
              {label}
            </text>
          ) : (
            <text key={ci} x={x} y={H - B + 20} textAnchor="middle" className={`${cls} text-[11px]`} style={isKhmer(c) ? { fontFamily: "Khmer OS Siemreap" } : undefined}>
              {label}
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
        {trend?.line && (
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block w-4 border-t-2 border-dashed border-text-dim" /> Trend{ahead.length > 0 ? " and forecast" : ""}
          </span>
        )}
        {trend?.moving_average && (
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block w-4 border-t-2 border-text-faint" /> {trend.moving_average}-period moving average
          </span>
        )}
        {result.labels.values.length > 1 && <span className="text-text-faint">Charting {text?.label}; the table shows every value.</span>}
      </div>
    </div>
  );
}

/** What a trend and an outlier check found, a line each, above the table or chart. */
export function StatsNotes({ result }: { result: PivotResult }) {
  const lines: { key: string; text: string }[] = [];
  const trend = result.trend;
  const name = (i: number) => result.labels.values[i]?.label ?? "";
  if (trend) {
    const many = trend.series.length > 1;
    trend.series.forEach((line, si) => {
      if (line.slope === undefined) return;
      let text = `Trend${many ? ` · ${keyText(result.column_keys[si])}` : ""}: ${line.slope >= 0 ? "+" : ""}${line.slope_t} per ${trend.per ?? "row"}`;
      if (line.r2 !== null && line.r2 !== undefined) text += ` · R² ${line.r2.toFixed(2)}`;
      if (line.forecast?.length) text += ` · forecast ${trend.forecast_keys.map((k, i) => `${k} ${line.forecast?.[i]?.t}`).join(", ")}`;
      lines.push({ key: `t${si}`, text });
    });
  }
  const outliers = result.outliers;
  if (outliers) {
    const how = outliers.method === "zscore" ? `more than ${outliers.threshold} standard deviations from the mean` : `beyond ${outliers.threshold} × IQR outside the quartiles`;
    outliers.values.forEach((o, i) =>
      lines.push({
        key: `o${i}`,
        text:
          o.low === null
            ? `Outliers in ${name(i)}: too few values to tell`
            : `Outliers in ${name(i)}: ${o.count} — below ${o.low_t} or above ${o.high_t} (${how})`,
      }),
    );
  }
  if (!lines.length) return null;
  return (
    <ul className="m-0 grid list-none gap-0.5 border-b border-border-soft px-3 py-2 text-[0.8rem] text-text-dim">
      {lines.map((l) => (
        <li key={l.key}>{l.text}</li>
      ))}
    </ul>
  );
}

export function PivotTable({ result }: { result: PivotResult }) {
  const { labels } = result;
  const values = labels.values;
  const hasColumns = labels.columns.length > 0;
  const cell = (entries: PivotValue[] | null | undefined) =>
    values.map((_, i) => {
      const e = entries?.[i];
      if (e?.o)
        return (
          <td key={i} className="analyze-outlier" title={`Outlier: unusually ${e.o}`}>
            {e.t}
          </td>
        );
      return (
        <td key={i} className={e && e.v !== null ? "" : "text-text-faint"}>
          {e && e.v !== null ? e.t : "—"}
        </td>
      );
    });
  // A forecast row per period ahead: the trend's value in each column, the rest left empty.
  const trend = result.trend;
  const followed = trend ? result.layout.values.indexOf(trend.value) : -1;
  const forecastRows = (trend?.forecast_keys ?? []).map((k, fi) => {
    const at = (si: number) => values.map((_, i) => (i === followed ? trend?.series[si]?.forecast?.[fi] : undefined));
    return { key: k, cells: hasColumns ? [...result.column_keys.map((_, si) => at(si)), values.map(() => undefined)] : [at(0)] };
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
          {forecastRows.map((row) => (
            <tr key={row.key} className="analyze-forecast">
              <td colSpan={Math.max(1, labels.rows.length)} className="text-left">
                {row.key} · forecast
              </td>
              {row.cells.flatMap((entries, ci) =>
                entries.map((e, i) => (
                  <td key={`${ci}-${i}`} className={e ? "" : "text-text-faint"}>
                    {e ? e.t : ""}
                  </td>
                )),
              )}
            </tr>
          ))}
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
  const sent = useMemo(() => sendable(layout), [layout]);

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
        .pivot(form.dataset, values, sent)
        .then((r) => {
          setResult(r);
          setError(null);
        })
        .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't work it out"))
        .finally(() => setRunning(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [form, values, sent]);

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
  function setShowAs(key: string, mode: ShowAsMode | "", along?: "rows" | "columns") {
    setLayout((prev) => {
      const show = { ...(prev.show_as ?? {}) };
      if (!mode) delete show[key];
      else show[key] = { mode, along: along ?? show[key]?.along ?? (prev.rows.length || !prev.columns.length ? "rows" : "columns") };
      return { ...prev, show_as: show };
    });
  }
  function setRange(name: string, width: number | null | undefined) {
    setLayout((prev) => {
      const ranges = { ...(prev.ranges ?? {}) };
      if (width === undefined) delete ranges[name];
      else ranges[name] = width;
      return { ...prev, ranges };
    });
  }
  function setTrend(change: Partial<NonNullable<PivotLayout["trend"]>>) {
    setLayout((prev) => {
      const next = { line: false, moving_average: null, forecast: 0, ...(prev.trend ?? {}), ...change };
      if (!next.line) next.forecast = 0;
      return { ...prev, trend: next.line || next.moving_average ? next : null };
    });
  }
  const toggleValue = (key: string) =>
    setLayout((prev) => ({ ...prev, values: prev.values.includes(key) ? prev.values.filter((k) => k !== key) : [...prev.values, key].slice(0, 6) }));

  async function exportAs(format: "pdf" | "docx" | "xlsx") {
    if (!form) return;
    setBusy(format);
    try {
      const { blob, filename } = await api.analyze.export({ dataset: form.dataset, values, layout: sent, format, chart, title: title.trim() || undefined });
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
      const body = { title: title.trim(), dataset: form.dataset, config: { values, layout: sent, view: chart } };
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
    try {
      await api.analyze.views.delete(v.id);
    } catch (err) {
      reportError(err, "Delete view");
      return;
    }
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
            {measureOptions.map((m) => {
              const shown = layout.values.includes(m.key);
              const spec = layout.show_as?.[m.key];
              return (
                <div key={m.key}>
                  <label className="checkbox-label mb-0 rounded-md px-1.5 py-1 hover:bg-bg-panel">
                    <input type="checkbox" checked={shown} onChange={() => toggleValue(m.key)} />
                    <span className="leading-tight">
                      {m.label}
                      {m.km && <small className="block text-[0.72rem] text-text-faint">{m.km}</small>}
                    </span>
                  </label>
                  {shown && (
                    <div className="mb-1 flex flex-wrap items-center gap-1 pl-7">
                      <select className="analyze-bucket" aria-label={`Show ${m.label} as`} value={spec?.mode ?? ""} onChange={(e) => setShowAs(m.key, e.target.value as ShowAsMode | "")}>
                        {SHOW_AS.map(([mode, label]) => (
                          <option key={mode} value={mode} disabled={SEQUENCE.includes(mode as ShowAsMode) && !layout.rows.length && !layout.columns.length}>
                            {label}
                          </option>
                        ))}
                      </select>
                      {spec && SEQUENCE.includes(spec.mode) && layout.rows.length > 0 && layout.columns.length > 0 && (
                        <select className="analyze-bucket" aria-label={`Run ${m.label} along`} value={spec.along} onChange={(e) => setShowAs(m.key, spec.mode, e.target.value as "rows" | "columns")}>
                          <option value="rows">down the rows</option>
                          <option value="columns">across the columns</option>
                        </select>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div>
            <h3 className="docs-home-label">Statistics</h3>
            <label className="checkbox-label mb-0 rounded-md px-1.5 py-1 hover:bg-bg-panel">
              <input type="checkbox" checked={!!layout.trend?.line} disabled={layout.rows.length !== 1} onChange={(e) => setTrend({ line: e.target.checked })} />
              <span className="leading-tight">Trend line</span>
            </label>
            <div className="grid grid-cols-2 gap-x-2 px-1.5">
              <label className="mb-1">
                <span className="text-[0.72rem]">Moving avg. (periods)</span>
                <select value={layout.trend?.moving_average ?? ""} disabled={layout.rows.length !== 1} onChange={(e) => setTrend({ moving_average: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">off</option>
                  {[2, 3, 4, 6, 12].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="mb-1">
                <span className="text-[0.72rem]">Forecast</span>
                <select value={layout.trend?.forecast ?? 0} disabled={!layout.trend?.line || layout.rows.length !== 1} onChange={(e) => setTrend({ forecast: Number(e.target.value) })}>
                  {[0, 1, 2, 3, 6, 12].map((n) => (
                    <option key={n} value={n}>
                      {n ? `${n} ahead` : "off"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {layout.trend && layout.values.length > 1 && (
              <label className="mb-1 px-1.5">
                <span className="text-[0.72rem]">Trend of</span>
                <select value={sent.trend?.value ?? layout.values[0]} onChange={(e) => setTrend({ value: e.target.value })}>
                  {layout.values.map((k) => (
                    <option key={k} value={k}>
                      {measureOptions.find((o) => o.key === k)?.label ?? k}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {layout.rows.length !== 1 && <p className="field-hint m-0 px-1.5">A trend runs down exactly one field in rows — a date by month, say.</p>}
            <div className="grid grid-cols-2 gap-x-2 px-1.5 pt-1">
              <label className="mb-1">
                <span className="text-[0.72rem]">Outliers</span>
                <select
                  value={layout.outliers?.method ?? ""}
                  onChange={(e) => setLayout((prev) => ({ ...prev, outliers: e.target.value ? { method: e.target.value as "zscore" | "iqr", threshold: null } : null }))}
                >
                  <option value="">off</option>
                  <option value="zscore">z-score</option>
                  <option value="iqr">IQR</option>
                </select>
              </label>
              {layout.outliers && (
                <label className="mb-1">
                  <span className="text-[0.72rem]">{layout.outliers.method === "zscore" ? "Std. deviations" : "× IQR"}</span>
                  <input
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={layout.outliers.threshold ?? (layout.outliers.method === "zscore" ? 2 : 1.5)}
                    onChange={(e) => setLayout((prev) => ({ ...prev, outliers: prev.outliers && { ...prev.outliers, threshold: Number(e.target.value) > 0 ? Math.min(10, Number(e.target.value)) : null } }))}
                  />
                </label>
              )}
            </div>
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
                    const isNumber = f?.type === "number" || f?.type === "money";
                    const width = layout.ranges?.[name];
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
                        {isNumber && (
                          <select
                            className="analyze-bucket"
                            aria-label={`Group ${fieldLabel(name)} into`}
                            value={width === undefined ? "" : width === null ? "auto" : "custom"}
                            onChange={(e) => setRange(name, e.target.value === "" ? undefined : e.target.value === "auto" ? null : (result?.ranges?.[name]?.width ?? 1000))}
                          >
                            <option value="">each value</option>
                            <option value="auto">in ranges{width === null && result?.ranges?.[name] ? ` of ${result.ranges[name].width_t}` : ""}</option>
                            <option value="custom">ranges of…</option>
                          </select>
                        )}
                        {isNumber && typeof width === "number" && (
                          <input
                            type="number"
                            className="analyze-bucket w-24"
                            aria-label={`Width of each ${fieldLabel(name)} range`}
                            min={0}
                            value={width}
                            onChange={(e) => Number(e.target.value) > 0 && setRange(name, Number(e.target.value))}
                          />
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
            {result && <StatsNotes result={result} />}
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
              layout={sent}
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
