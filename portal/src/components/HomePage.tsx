import { useEffect, useMemo, useState } from "react";
import { BookOpen, CalendarClock, FileText, Play, ShieldCheck, Star } from "lucide-react";
import { api } from "../api";
import { has } from "../admin/sections";
import { useFavoriteReports } from "../favorites";
import type { Route } from "../hooks";
import type { AccessibleReport, AuthInfo, MyDashboard } from "../types";
import { LinesSkeleton, StatRowSkeleton } from "./Skeletons";

/** "5 minutes ago" / "yesterday" / a date -- how long ago something happened. */
function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 172_800) return "yesterday";
  return new Date(iso).toLocaleDateString();
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Everyone's landing page: what *they* have been doing, the reports they use most, and the shortcuts they
 * are likely to want. The numbers come from GET /me/dashboard (only the caller's own runs); what they may
 * open comes from the accessible-reports list, so a report they've since lost access to is shown but can't
 * be run from here. */
export default function HomePage({
  auth,
  canAdmin,
  navigate,
}: {
  auth: AuthInfo;
  canAdmin: boolean;
  navigate: (route: Route) => void;
}) {
  const [mine, setMine] = useState<MyDashboard | null>(null);
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const [failed, setFailed] = useState(false);
  const { favorites, toggle } = useFavoriteReports(auth.username);

  useEffect(() => {
    api.me.dashboard().then(setMine).catch(() => setFailed(true));
    api.listAccessibleReports().then(setReports).catch(() => setReports([]));
  }, []);

  const runnable = useMemo(() => new Map((reports ?? []).filter((r) => r.access_level !== "view").map((r) => [r.report_id, r])), [reports]);
  const starred = favorites.map((id) => runnable.get(id)).filter((r): r is AccessibleReport => Boolean(r));
  const run = (id: string) => navigate({ view: "run", id });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Welcome back, {auth.username}</h1>
          <p className="page-subtitle">
            {mine?.last_run_at ? `You last ran a report ${ago(mine.last_run_at)}.` : "Your recent activity and shortcuts."}
          </p>
        </div>
      </div>

      <div className="stack" style={{ gap: 20 }}>
        <div className="panel" style={{ margin: 0 }}>
          <span className="panel-title" style={{ fontSize: "1rem" }}>
            Your activity
          </span>
          {failed && <p className="alert alert-error">Couldn't load your activity.</p>}
          {!mine && !failed && <StatRowSkeleton count={4} />}
          {mine && (
            <div className="stat-row">
              <Stat value={mine.runs_7d} label="runs this week" />
              <Stat value={mine.runs_30d} label="runs in 30 days" />
              <Stat value={mine.failed_30d} label="failed in 30 days" />
              <Stat value={reports ? reports.length : "…"} label="reports you can see" />
            </div>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 20, alignItems: "start" }}>
          <div className="panel" style={{ margin: 0 }}>
            <div className="spread" style={{ marginBottom: 8 }}>
              <span className="panel-title" style={{ fontSize: "1rem" }}>
                Starred reports
              </span>
            </div>
            {reports === null && <LinesSkeleton count={3} />}
            {reports !== null && starred.length === 0 && (
              <p className="muted">
                Nothing starred yet. Press <Star size={13} style={{ display: "inline", verticalAlign: "-2px" }} aria-hidden="true" /> on a report in{" "}
                <a className="link-btn" href="#/reports">
                  Reports
                </a>{" "}
                to keep it here.
              </p>
            )}
            {starred.map((r) => (
              <ReportLine key={r.report_id} name={r.name} hint={r.description} onRun={() => run(r.report_id)} onUnstar={() => toggle(r.report_id)} />
            ))}
          </div>

          <div className="panel" style={{ margin: 0 }}>
            <span className="panel-title" style={{ fontSize: "1rem" }}>
              Most used
            </span>
            {!mine && !failed && <LinesSkeleton count={3} />}
            {mine && mine.top_reports.length === 0 && <p className="muted">Reports you run will show up here.</p>}
            {mine?.top_reports.map((t) => {
              const known = runnable.get(t.report_id);
              return (
                <ReportLine
                  key={t.report_id}
                  name={known?.name ?? t.name ?? t.report_id}
                  hint={plural(t.runs, "run") + " in 30 days"}
                  onRun={known ? () => run(t.report_id) : undefined}
                />
              );
            })}
          </div>
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <span className="panel-title" style={{ fontSize: "1rem" }}>
            Recent runs
          </span>
          {!mine && !failed && <LinesSkeleton count={4} />}
          {mine && mine.recent.length === 0 && <p className="muted">You haven't run a report yet. Pick one from Reports to get started.</p>}
          {mine && mine.recent.length > 0 && (
            <div className="stack">
              {mine.recent.map((r, i) => {
                const known = runnable.get(r.report_id);
                return (
                  <div key={i} className="spread" style={{ gap: 12, padding: "8px 0", borderTop: i ? "1px solid var(--border-soft)" : undefined }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 500 }}>{known?.name ?? r.name ?? r.report_id}</div>
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        {ago(r.at)}
                        {r.parameters_selected != null && ` · ${plural(r.parameters_selected, "filter")} chosen`}
                        {r.format && ` · ${r.format.toUpperCase()}`}
                        {!r.ok && <span style={{ color: "var(--danger, #b3261e)" }}> · didn't finish{r.reason ? ` (${r.reason})` : ""}</span>}
                      </div>
                    </div>
                    {known && (
                      <button type="button" className="btn" onClick={() => run(r.report_id)} aria-label={`Run ${known.name} again`}>
                        <Play size={14} aria-hidden="true" /> Run again
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <span className="panel-title" style={{ fontSize: "1rem" }}>
            Shortcuts
          </span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 10 }}>
            <Shortcut icon={<FileText size={15} />} label="All reports" onClick={() => navigate({ view: "reports" })} />
            <Shortcut icon={<BookOpen size={15} />} label="Guides" onClick={() => navigate({ view: "docs" })} />
            {has(auth, "job:view") && <Shortcut icon={<CalendarClock size={15} />} label="Schedules" onClick={() => navigate({ view: "schedules" })} />}
            {canAdmin && <Shortcut icon={<ShieldCheck size={15} />} label="Admin console" onClick={() => navigate({ view: "admin", section: "dashboard" })} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div>
      <div className="mono stat-number">{value}</div>
      <div className="muted">{label}</div>
    </div>
  );
}

function Shortcut({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button type="button" className="btn" onClick={onClick}>
      {icon} {label}
    </button>
  );
}

function ReportLine({ name, hint, onRun, onUnstar }: { name: string; hint?: string | null; onRun?: () => void; onUnstar?: () => void }) {
  return (
    <div className="spread" style={{ gap: 12, padding: "8px 0" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
        {hint && (
          <div className="muted" style={{ fontSize: "0.8rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {hint}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flex: "none" }}>
        {onUnstar && (
          <button type="button" className="star-btn starred" onClick={onUnstar} aria-label={`Remove ${name} from starred`} data-tip="Unstar">
            <Star size={16} fill="currentColor" aria-hidden="true" />
          </button>
        )}
        {onRun && (
          <button type="button" className="btn" onClick={onRun}>
            <Play size={14} aria-hidden="true" /> Run
          </button>
        )}
      </div>
    </div>
  );
}
