import { Play, Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useFavoriteReports } from "../favorites";
import type { Route } from "../hooks";
import type { AccessibleReport } from "../types";
import { LinesSkeleton } from "./Skeletons";

/** #/starred -- the reports a person starred (kept in this browser, see favorites.ts), one click to run.
 * A starred report they can no longer run is left out, the same as on Home. */
export default function StarredPage({ username, navigate }: { username: string; navigate: (route: Route) => void }) {
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const { favorites, toggle } = useFavoriteReports(username);

  useEffect(() => {
    api.listAccessibleReports().then(setReports).catch(() => setReports([]));
  }, []);

  const starred = useMemo(() => {
    const runnable = new Map((reports ?? []).filter((r) => r.access_level !== "view").map((r) => [r.report_id, r]));
    return favorites.map((id) => runnable.get(id)).filter((r): r is AccessibleReport => Boolean(r));
  }, [reports, favorites]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Starred</h1>
          <p className="page-subtitle">The reports you keep coming back to. Star more in Reports.</p>
        </div>
      </div>

      <section className="home-card">
        {reports === null && <LinesSkeleton count={4} />}
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
          <div key={r.report_id} className="spread home-line" style={{ gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</div>
              {r.description && (
                <div className="muted" style={{ fontSize: "0.8rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.description}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, flex: "none" }}>
              <button type="button" className="star-btn starred" onClick={() => toggle(r.report_id)} aria-label={`Remove ${r.name} from starred`} data-tip="Unstar">
                <Star size={16} fill="currentColor" aria-hidden="true" />
              </button>
              <button type="button" className="btn" onClick={() => navigate({ view: "run", id: r.report_id })}>
                <Play size={14} aria-hidden="true" /> Run
              </button>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
