import { Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Route } from "../hooks";
import { ago, plural } from "../relativeTime";
import type { AccessibleReport, MyRun } from "../types";
import { LinesSkeleton } from "./Skeletons";

/** #/runs -- the signed-in person's own report runs, newest first (GET /me/runs): Home's "Recent runs", further
 * back. Each one can be run again; one whose report they can no longer run just says so. */
export default function MyRunsPage({ navigate }: { navigate: (route: Route) => void }) {
  const [runs, setRuns] = useState<MyRun[] | null>(null);
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.me.runs(200).then(setRuns).catch(() => setFailed(true));
    api.listAccessibleReports().then(setReports).catch(() => setReports([]));
  }, []);

  const runnable = useMemo(
    () => new Map((reports ?? []).filter((r) => r.access_level !== "view").map((r) => [r.report_id, r])),
    [reports],
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">My runs</h1>
          <p className="page-subtitle">Every report you've run, newest first — run one again with a click.</p>
        </div>
      </div>

      <section className="home-card">
        {failed && <p className="alert alert-error">Couldn't load your runs. Try again in a moment.</p>}
        {!failed && runs === null && <LinesSkeleton count={6} />}
        {runs !== null && runs.length === 0 && (
          <p className="muted">
            You haven't run a report yet.{" "}
            <a className="link-btn" href="#/reports">
              Pick one from Reports
            </a>{" "}
            to get started.
          </p>
        )}
        {runs !== null && runs.length > 0 && (
          <div className="stack">
            {runs.map((r, i) => {
              const known = runnable.get(r.report_id);
              return (
                <div key={i} className="spread home-run-row" style={{ gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 500 }}>{known?.name ?? r.name ?? r.report_id}</div>
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      {ago(r.at)}
                      {r.parameters_selected != null && ` · ${plural(r.parameters_selected, "filter")} chosen`}
                      {r.format && ` · ${r.format.toUpperCase()}`}
                      {!r.ok && <span style={{ color: "var(--danger)" }}> · didn't finish{r.reason ? ` (${r.reason})` : ""}</span>}
                    </div>
                  </div>
                  {known ? (
                    <button type="button" className="btn" onClick={() => navigate({ view: "run", id: r.report_id })} aria-label={`Run ${known.name} again`}>
                      <Play size={14} aria-hidden="true" /> Run again
                    </button>
                  ) : (
                    reports !== null && <span className="muted" style={{ fontSize: "0.8rem" }}>No longer available to you</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
