import { useEffect, useState } from "react";
import { BellRing, LayoutDashboard } from "lucide-react";
import { api, ApiError } from "../api";
import type { AnalysisChart, AnalyzeForm, ConnectionSummary, DashboardSummary, PivotLayout, TileView } from "../types";

/** What a view in Analyze can become: a tile on a dashboard, or a data alert (a job that watches one measure and
 * emails when it crosses a threshold -- api/app/data_alerts.py). */

const tileId = () => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export function AddToDashboard({
  form,
  values,
  layout,
  chart,
  title,
  onDone,
}: {
  form: AnalyzeForm;
  values: Record<string, string>;
  layout: PivotLayout;
  chart: AnalysisChart;
  title: string;
  onDone: (message: string, dashboardId: string) => void;
}) {
  const [mine, setMine] = useState<DashboardSummary[] | null>(null);
  const [target, setTarget] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [tileTitle, setTileTitle] = useState(title || form.title);
  const kpiAllowed = layout.rows.length === 0 && layout.columns.length === 0;
  const [view, setView] = useState<TileView>(kpiAllowed ? "kpi" : chart);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboards
      .list()
      .then((list) => {
        const own = list.filter((d) => d.mine);
        setMine(own);
        setTarget(own[0]?.id ?? "new");
      })
      .catch(() => setMine([]));
  }, []);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const id = target === "new" ? (await api.dashboards.create(newTitle.trim() || "My dashboard")).id : target;
      const dashboard = await api.dashboards.get(id);
      const tile = { id: tileId(), title: tileTitle.trim() || form.title, dataset: form.dataset, values, layout, view, width: (view === "kpi" ? 1 : 2) as 1 | 2 };
      await api.dashboards.update(id, { title: dashboard.title, description: dashboard.description, tiles: [...dashboard.tiles, tile], filters: dashboard.filters });
      onDone(`Added “${tile.title}” to ${dashboard.title}`, id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add it");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-3 rounded-[12px] border border-accent-border bg-bg-raised p-4">
      <b className="flex items-center gap-2 font-semibold">
        <LayoutDashboard size={16} aria-hidden="true" /> Add to a dashboard
      </b>
      <div className="grid grid-cols-1 gap-x-3 sm:grid-cols-3">
        <label>
          <span>Dashboard</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {mine?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
              </option>
            ))}
            <option value="new">A new dashboard…</option>
          </select>
        </label>
        {target === "new" ? (
          <label>
            <span>Its name</span>
            <input type="text" maxLength={120} placeholder="Daily sales" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
          </label>
        ) : (
          <span />
        )}
        <label>
          <span>Show as</span>
          <select value={view} onChange={(e) => setView(e.target.value as TileView)}>
            {kpiAllowed && <option value="kpi">A number (KPI)</option>}
            <option value="table">Table</option>
            <option value="bar">Bar chart</option>
            <option value="line">Line chart</option>
          </select>
        </label>
      </div>
      <label className="mb-0">
        <span>Tile title</span>
        <input type="text" maxLength={120} value={tileTitle} onChange={(e) => setTileTitle(e.target.value)} />
      </label>
      {!kpiAllowed && <p className="field-hint m-0">For a single big number, take the fields out of rows and columns first.</p>}
      {error && <p className="alert alert-error m-0">{error}</p>}
      <div>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void add()} disabled={busy || mine === null}>
          {busy && <span className="spinner" />} Add tile
        </button>
      </div>
    </div>
  );
}

const SCHEDULES = [
  { cron: "0 * * * *", label: "Every hour" },
  { cron: "0 8 * * *", label: "Every day at 08:00" },
  { cron: "0 8 * * 1-5", label: "Weekdays at 08:00" },
  { cron: "0 8 * * 1", label: "Mondays at 08:00" },
];

export function AlertMe({
  form,
  values,
  orgId,
  onDone,
}: {
  form: AnalyzeForm;
  values: Record<string, string>;
  orgId: string;
  onDone: (message: string) => void;
}) {
  const options = [...form.measures.map((m) => ({ key: m.key, label: m.label })), { key: "__rows", label: "Rows (count)" }];
  const [measure, setMeasure] = useState(options[0].key);
  const [condition, setCondition] = useState<"below" | "above" | "outlier">("below");
  const [threshold, setThreshold] = useState("");
  // Branches, products… first: comparing single days is rarely what's meant.
  const groupable = ["text", "boolean", "date"].flatMap((type) => form.fields.filter((f) => f.type === type));
  const [groupBy, setGroupBy] = useState(groupable[0]?.name ?? "");
  const [method, setMethod] = useState<"zscore" | "iqr">("zscore");
  const [cron, setCron] = useState(SCHEDULES[1].cron);
  const [servers, setServers] = useState<ConnectionSummary[] | null>(null);
  const [server, setServer] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.connections
      .list()
      .then((list) => {
        const smtp = list.filter((c) => c.kind === "smtp");
        setServers(smtp);
        setServer(smtp[0]?.name ?? "");
      })
      .catch(() => setServers([]));
  }, []);

  const number = Number(threshold.replace(/[,\s៛$%]/g, ""));
  const outlier = condition === "outlier";
  const ready = (outlier ? groupBy : threshold.trim() !== "" && Number.isFinite(number)) && server && to.trim();
  const groupLabel = groupable.find((f) => f.name === groupBy)?.label || groupBy;
  const label = options.find((o) => o.key === measure)?.label ?? measure;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.jobs.create(orgId, {
        name: (outlier ? `Alert: ${form.title} · a ${groupLabel} stands out on ${label}` : `Alert: ${form.title} · ${label} ${condition} ${threshold.trim()}`).slice(0, 120),
        job_type: "data_alert",
        trigger_type: "cron",
        cron_expression: cron,
        config: {
          dataset: form.dataset, values, measure, condition, repeat: "on_change",
          ...(outlier ? { group_by: groupBy, method } : { threshold: number }),
          email: { connection: server, to: to.split(/[,;\s]+/).filter(Boolean) },
        },
      });
      onDone(
        outlier
          ? `Alert set: you'll get an email when a ${groupLabel} stands out from the rest on ${label}.`
          : `Alert set: you'll get an email when ${label} ${condition === "below" ? "drops below" : "rises above"} ${threshold.trim()}.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't set the alert");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-3 rounded-[12px] border border-accent-border bg-bg-raised p-4">
      <b className="flex items-center gap-2 font-semibold">
        <BellRing size={16} aria-hidden="true" /> Alert me when…
      </b>
      <div className="grid grid-cols-1 gap-x-3 sm:grid-cols-3">
        <label>
          <span>Measure</span>
          <select value={measure} onChange={(e) => setMeasure(e.target.value)}>
            {options.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Goes</span>
          <select value={condition} onChange={(e) => setCondition(e.target.value as "below" | "above" | "outlier")}>
            <option value="below">Below</option>
            <option value="above">Above</option>
            <option value="outlier" disabled={groupable.length === 0}>
              Stands out for one…
            </option>
          </select>
        </label>
        {outlier ? (
          <>
            <label>
              <span>Compare each</span>
              <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
                {groupable.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.label || f.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Outlier by</span>
              <select value={method} onChange={(e) => setMethod(e.target.value as "zscore" | "iqr")}>
                <option value="zscore">z-score (beyond 2 std. dev.)</option>
                <option value="iqr">IQR (beyond 1.5 × IQR)</option>
              </select>
            </label>
          </>
        ) : (
          <label>
            <span>Threshold</span>
            <input type="text" inputMode="decimal" placeholder="50,000,000" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </label>
        )}
        <label>
          <span>Check</span>
          <select value={cron} onChange={(e) => setCron(e.target.value)}>
            {SCHEDULES.map((s) => (
              <option key={s.cron} value={s.cron}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Mail server</span>
          <select value={server} onChange={(e) => setServer(e.target.value)}>
            {servers?.length === 0 && <option value="">None yet — add one under Manage → Connections</option>}
            {servers?.map((s) => (
              <option key={s.id} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Email to</span>
          <input type="text" placeholder="finance@example.com" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      <p className="field-hint m-0">
        {outlier
          ? `It works ${label} out for each ${groupLabel} with the filters set above and emails when one stands out from the rest — no number to pick. Not again until none does.`
          : "It checks with the filters set above, across all the data, and emails when it first crosses — not again until it has recovered."}{" "}
        Change or stop it under Manage → Jobs.
      </p>
      {error && <p className="alert alert-error m-0">{error}</p>}
      <div>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void create()} disabled={busy || !ready}>
          {busy && <span className="spinner" />} Set the alert
        </button>
      </div>
    </div>
  );
}
