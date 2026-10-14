import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, ChartColumnBig, LayoutDashboard, Pencil, Plus, RefreshCw, Share2, Trash2, Users } from "lucide-react";
import { api, ApiError } from "../api";
import { has } from "../admin/sections";
import type { Route } from "../hooks";
import type { AuthInfo, Dashboard, DashboardSummary, DashboardTile, PivotResult, Role, TileView } from "../types";
import { Chart, PivotTable } from "./AnalyzePage";
import ConfirmDialog from "./ConfirmDialog";
import { ParameterField } from "./RunReportPage";

/** Dashboards (api/app/dashboards.py): Analyze views as tiles on one page, the filters they share across the top.
 * Everyone sees the dashboards they own or that are shared with their roles; each tile shows *their* data -- a
 * restricted dataset still only gives them their values. Owners arrange, resize and share them. */

const VIEW_LABEL: Record<TileView, string> = { table: "Table", bar: "Bar chart", line: "Line chart", kpi: "Number (KPI)" };
// Written out whole for Tailwind's scanner.
const SPAN: Record<1 | 2 | 3, string> = { 1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3" };

function TileBody({ tile, result }: { tile: DashboardTile; result: PivotResult }) {
  if (tile.view === "kpi") {
    const [first, ...rest] = result.total;
    const labels = result.labels.values;
    return (
      <div className="grid gap-2 px-4 pb-4">
        <div className="text-[2rem] leading-tight font-semibold tracking-[-0.02em] tabular-nums">{first?.v !== null ? first?.t : "—"}</div>
        <div className="text-[0.8rem] text-text-dim">{labels[0]?.label_km || labels[0]?.label}</div>
        {rest.length > 0 && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-border-soft pt-2 text-[0.82rem]">
            {rest.map((v, i) => (
              <span key={i}>
                <span className="text-text-faint">{labels[i + 1]?.label}: </span>
                <b className="font-semibold tabular-nums">{v.v !== null ? v.t : "—"}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (tile.view === "table") return <PivotTable result={result} />;
  return <Chart result={result} kind={tile.view} />;
}

function Tile({
  dashboard,
  tile,
  filters,
  refresh,
  editing,
  onChange,
  onMove,
  onRemove,
  first,
  last,
}: {
  dashboard: Dashboard;
  tile: DashboardTile;
  filters: Record<string, string>;
  refresh: number;
  editing: boolean;
  onChange: (patch: Partial<DashboardTile>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  first: boolean;
  last: boolean;
}) {
  const [result, setResult] = useState<PivotResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const filterKey = JSON.stringify(filters);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.dashboards
      .runTile(dashboard.id, tile.id, filters)
      .then((r) => {
        if (!live) return;
        setResult(r);
        setError(null);
      })
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load this tile"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run when the filters' values or the refresh count change
  }, [dashboard.id, tile.id, filterKey, refresh, tile.view]);

  const kpiAllowed = tile.layout.rows.length === 0 && tile.layout.columns.length === 0;
  return (
    <section className={`col-span-1 ${SPAN[tile.width]} grid min-w-0 content-start overflow-hidden rounded-[12px] border border-border-soft bg-bg-raised`}>
      <header className="flex items-center gap-2 px-4 pt-3 pb-2">
        {editing ? (
          <input type="text" className="h-8 flex-1 py-1 text-[0.9rem] font-semibold" maxLength={120} value={tile.title} onChange={(e) => onChange({ title: e.target.value })} aria-label="Tile title" />
        ) : (
          <h2 className="m-0 min-w-0 flex-1 truncate text-[0.95rem] font-semibold">{tile.title}</h2>
        )}
        {loading && <span className="spinner" aria-label="Loading" />}
      </header>
      {editing && (
        <div className="flex flex-wrap items-center gap-1.5 border-y border-border-soft bg-bg-panel px-4 py-2">
          <select className="h-8 w-auto py-1 text-[0.8rem]" value={tile.view} onChange={(e) => onChange({ view: e.target.value as TileView })} aria-label="Show as">
            {(Object.keys(VIEW_LABEL) as TileView[])
              .filter((v) => v !== "kpi" || kpiAllowed)
              .map((v) => (
                <option key={v} value={v}>
                  {VIEW_LABEL[v]}
                </option>
              ))}
          </select>
          <select className="h-8 w-auto py-1 text-[0.8rem]" value={tile.width} onChange={(e) => onChange({ width: Number(e.target.value) as 1 | 2 | 3 })} aria-label="Width">
            <option value={1}>Narrow</option>
            <option value={2}>Wide</option>
            <option value={3}>Full width</option>
          </select>
          <span className="flex-1" />
          <button type="button" className="btn btn-ghost btn-sm icon-only" disabled={first} onClick={() => onMove(-1)} aria-label="Move earlier">
            <ArrowUp size={14} />
          </button>
          <button type="button" className="btn btn-ghost btn-sm icon-only" disabled={last} onClick={() => onMove(1)} aria-label="Move later">
            <ArrowDown size={14} />
          </button>
          <button type="button" className="btn btn-ghost btn-sm icon-only" onClick={onRemove} aria-label={`Remove ${tile.title}`}>
            <Trash2 size={14} />
          </button>
        </div>
      )}
      {error ? (
        <p className="m-4 text-[0.85rem] text-text-dim">{error}</p>
      ) : result ? (
        <TileBody tile={tile} result={result} />
      ) : (
        <div className="h-24" />
      )}
    </section>
  );
}

function ShareDialog({ dashboard, onClose, onSaved }: { dashboard: Dashboard; onClose: () => void; onSaved: (d: Dashboard) => void }) {
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [chosen, setChosen] = useState<string[]>(dashboard.shared_role_ids);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.roles.list(dashboard.org_id).then(setRoles).catch(() => setRoles([]));
  }, [dashboard.org_id]);
  async function save() {
    try {
      onSaved(await api.dashboards.share(dashboard.id, chosen));
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't share it");
    }
  }
  return (
    <div className="grid gap-3 rounded-[12px] border border-accent-border bg-bg-raised p-4">
      <b className="font-semibold">Share “{dashboard.title}”</b>
      <p className="field-hint m-0">
        People in these roles can open it — not change it. Each sees every tile with their own access: a restricted dataset still only gives
        them their values.
      </p>
      {roles === null ? (
        <span className="spinner" />
      ) : roles.length === 0 ? (
        <p className="field-hint m-0">Listing roles needs the role:manage permission.</p>
      ) : (
        <div className="grid gap-1 sm:grid-cols-2">
          {roles.map((r) => (
            <label key={r.id} className="checkbox-label mb-0">
              <input type="checkbox" checked={chosen.includes(r.id)} onChange={(e) => setChosen((prev) => (e.target.checked ? [...prev, r.id] : prev.filter((x) => x !== r.id)))} />
              {r.name}
            </label>
          ))}
        </div>
      )}
      {error && <p className="alert alert-error m-0">{error}</p>}
      <div className="flex gap-2">
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void save()}>
          Save sharing
        </button>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function DashboardView({ id, auth, navigate }: { id: string; auth: AuthInfo; navigate: (r: Route) => void }) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{ title: string; tiles: DashboardTile[] } | null>(null);
  const [sharing, setSharing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.dashboards
      .get(id)
      .then((d) => {
        setDashboard(d);
        // The page's filters start from the dashboard's own, then the first value each filter offers.
        const start: Record<string, string> = {};
        for (const p of d.filter_bar) start[p.name] = d.filters[p.name] ?? p.options?.[0]?.value ?? "";
        setFilters(start);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't open the dashboard"));
  }, [id]);

  const tiles = editing && draft ? draft.tiles : (dashboard?.tiles ?? []);
  const setTile = (tileId: string, patch: Partial<DashboardTile>) => setDraft((d) => d && { ...d, tiles: d.tiles.map((t) => (t.id === tileId ? { ...t, ...patch } : t)) });
  const move = (index: number, delta: -1 | 1) =>
    setDraft((d) => {
      if (!d) return d;
      const next = [...d.tiles];
      const [item] = next.splice(index, 1);
      next.splice(index + delta, 0, item);
      return { ...d, tiles: next };
    });

  async function save() {
    if (!dashboard || !draft) return;
    setSaving(true);
    try {
      const saved = await api.dashboards.update(dashboard.id, { title: draft.title.trim() || dashboard.title, description: dashboard.description, tiles: draft.tiles, filters });
      setDashboard(saved);
      setEditing(false);
      setDraft(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the dashboard");
    } finally {
      setSaving(false);
    }
  }

  if (error && !dashboard) return <p className="alert alert-error">{error}</p>;
  if (!dashboard) return <span className="spinner" />;
  return (
    <div className="grid gap-4">
      <button type="button" className="link-btn inline-flex items-center gap-1.5 justify-self-start text-[0.85rem]" onClick={() => navigate({ view: "dashboards" })}>
        <ArrowLeft size={14} aria-hidden="true" /> All dashboards
      </button>
      <div className="page-header">
        <div className="min-w-0 flex-1">
          {editing && draft ? (
            <input type="text" className="text-[1.4rem] font-semibold" maxLength={120} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} aria-label="Dashboard title" />
          ) : (
            <h1 className="page-title">{dashboard.title}</h1>
          )}
          <p className="page-subtitle">
            {dashboard.can_edit ? "Yours" : `By ${dashboard.owner}`}
            {dashboard.shared_role_ids.length > 0 && ` · shared with ${dashboard.shared_role_ids.length} role${dashboard.shared_role_ids.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="page-header-actions flex-wrap">
          <button type="button" className="btn" onClick={() => setRefresh((n) => n + 1)}>
            <RefreshCw size={14} aria-hidden="true" /> Refresh
          </button>
          {dashboard.can_edit && !editing && (
            <>
              <button type="button" className="btn" onClick={() => setSharing(true)}>
                <Share2 size={14} aria-hidden="true" /> Share
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setDraft({ title: dashboard.title, tiles: dashboard.tiles });
                  setEditing(true);
                }}
              >
                <Pencil size={14} aria-hidden="true" /> Edit
              </button>
            </>
          )}
          {editing && (
            <>
              <button type="button" className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
                <Trash2 size={14} aria-hidden="true" /> Delete
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setEditing(false);
                  setDraft(null);
                }}
              >
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving}>
                {saving && <span className="spinner" />} Save
              </button>
            </>
          )}
        </div>
      </div>
      {error && <p className="alert alert-error m-0">{error}</p>}
      {sharing && <ShareDialog dashboard={dashboard} onClose={() => setSharing(false)} onSaved={setDashboard} />}

      {dashboard.filter_bar.length > 0 && (
        <div className="flex flex-wrap items-end gap-3 rounded-[12px] border border-border-soft bg-bg-raised p-3">
          {dashboard.filter_bar.map((p) => (
            <div key={p.name} className="analyze-filter min-w-[11rem]">
              <ParameterField parameter={p} value={filters[p.name] ?? ""} onChange={(next) => setFilters((prev) => ({ ...prev, [p.name]: next }))} />
            </div>
          ))}
          {editing && <span className="field-hint m-0 self-center">Saving keeps these values as the dashboard's starting filters.</span>}
        </div>
      )}

      {tiles.length === 0 ? (
        <div className="empty-state">
          <LayoutDashboard size={30} strokeWidth={1.4} aria-hidden="true" />
          <p>No tiles yet.</p>
          <p className="muted">
            {has(auth, "analyze:use") ? (
              <>
                Open <a href="#/analyze">Explore data</a>, arrange a view, and choose <em>Add to dashboard</em>.
              </>
            ) : (
              "Its owner adds them from Explore data."
            )}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
          {tiles.map((tile, i) => (
            <Tile
              key={tile.id}
              dashboard={dashboard}
              tile={tile}
              filters={filters}
              refresh={refresh}
              editing={editing}
              onChange={(patch) => setTile(tile.id, patch)}
              onMove={(delta) => move(i, delta)}
              onRemove={() => setDraft((d) => d && { ...d, tiles: d.tiles.filter((t) => t.id !== tile.id) })}
              first={i === 0}
              last={i === tiles.length - 1}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete dashboard"
        body={`Delete “${dashboard.title}”? Its tiles go with it; the datasets and saved views stay.`}
        confirmLabel="Delete"
        onConfirm={async () => {
          setConfirmDelete(false);
          await api.dashboards.delete(dashboard.id).catch(() => {});
          navigate({ view: "dashboards" });
        }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

export default function DashboardsPage({ auth, dashboardId, navigate }: { auth: AuthInfo; dashboardId?: string; navigate: (r: Route) => void }) {
  const [list, setList] = useState<DashboardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const canMake = has(auth, "analyze:use");

  useEffect(() => {
    if (dashboardId) return;
    api.dashboards.list().then(setList).catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the dashboards"));
  }, [dashboardId]);

  const groups = useMemo(() => ({ mine: (list ?? []).filter((d) => d.mine), shared: (list ?? []).filter((d) => !d.mine) }), [list]);

  async function create() {
    try {
      const d = await api.dashboards.create(title.trim());
      navigate({ view: "dashboards", id: d.id });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't make the dashboard");
    }
  }

  if (dashboardId) return <DashboardView key={dashboardId} id={dashboardId} auth={auth} navigate={navigate} />;

  const card = (d: DashboardSummary) => (
    <button
      key={d.id}
      type="button"
      className="grid gap-1.5 rounded-[12px] border border-border-soft bg-bg-raised p-4 text-left hover:border-accent-border"
      onClick={() => navigate({ view: "dashboards", id: d.id })}
    >
      <span className="flex items-center gap-2 font-semibold">
        <LayoutDashboard size={16} className="text-accent-strong" aria-hidden="true" /> {d.title}
      </span>
      <span className="text-[0.8rem] text-text-dim">
        {d.tile_count} tile{d.tile_count === 1 ? "" : "s"} · {d.mine ? "yours" : `by ${d.owner}`}
        {d.mine && d.shared && (
          <span className="ml-1.5 inline-flex items-center gap-1 text-text-faint">
            <Users size={12} aria-hidden="true" /> shared
          </span>
        )}
      </span>
    </button>
  );

  return (
    <div className="grid gap-5">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboards</h1>
          <p className="page-subtitle">The numbers you watch, on one page — each tile with your own access to its data.</p>
        </div>
        {canMake && (
          <div className="page-header-actions">
            <button type="button" className="btn" onClick={() => navigate({ view: "analyze" })}>
              <ChartColumnBig size={14} aria-hidden="true" /> Explore data
            </button>
          </div>
        )}
      </div>
      {error && <p className="alert alert-error m-0">{error}</p>}
      {list === null && !error && <span className="spinner" />}
      {canMake && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) void create();
          }}
        >
          <label className="mb-0 min-w-[16rem] flex-1">
            <span>New dashboard</span>
            <input type="text" maxLength={120} placeholder="Daily sales" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={!title.trim()}>
            <Plus size={14} aria-hidden="true" /> Make it
          </button>
        </form>
      )}
      {list !== null && list.length === 0 && (
        <div className="empty-state">
          <LayoutDashboard size={30} strokeWidth={1.4} aria-hidden="true" />
          <p>No dashboards yet.</p>
          <p className="muted">{canMake ? "Make one above, then add tiles from Explore data." : "When someone shares a dashboard with one of your roles, it appears here."}</p>
        </div>
      )}
      {groups.mine.length > 0 && (
        <section className="grid gap-2">
          <h2 className="docs-home-label">Yours</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{groups.mine.map(card)}</div>
        </section>
      )}
      {groups.shared.length > 0 && (
        <section className="grid gap-2">
          <h2 className="docs-home-label">Shared with you</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{groups.shared.map(card)}</div>
        </section>
      )}
    </div>
  );
}
