import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { api } from "../../api";
import TermChips from "../../components/TermChips";
import { LinesSkeleton } from "../../components/Skeletons";
import type { DeploymentTerms } from "../../types";

// The four env-var-pointed locations the API reads the list from
// (api/app/deployment_terms_sync.py's `source_paths`), in plain words.
const SOURCE_LABELS: [string, string][] = [
  ["terms_file", "Protected terms file"],
  ["terms_dir", "Protected terms folder"],
  ["exclude_file", "Exclusions file"],
  ["exclude_dir", "Exclusions folder"],
];

/** Read-only view of the deployment-wide list: the terms every report in
 * every organization gets, no matter what. It lives in config files mounted
 * on the API server and is mirrored into the database at each boot -- so
 * this panel shows *what the server currently has* and says plainly that
 * the way to change it is on the server, not here. */
export default function DeploymentTermsPanel() {
  const [floor, setFloor] = useState<DeploymentTerms | null | undefined>(undefined);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.protectedTerms.deploymentFloor().then(setFloor).catch(() => setFloor(null));
  }, []);

  if (floor === undefined) {
    return (
      <section className="panel terms-floor" aria-busy="true">
        <LinesSkeleton count={2} />
      </section>
    );
  }
  // Not synced yet, or not visible to this caller -- nothing useful to say.
  if (floor === null) return null;

  const sources = SOURCE_LABELS.filter(([key]) => floor.source_paths[key]);
  const total = floor.terms.length + floor.exclude_terms.length;

  return (
    <section className="panel terms-floor">
      <div className="terms-floor-head">
        <div>
          <h2 className="panel-title terms-floor-title">
            Deployment-wide list
            <span className="badge badge-system" title="Bumps each time the config files change between API restarts">
              v{floor.version}
            </span>
          </h2>
          <p className="panel-subtitle terms-floor-sub">
            Applied to <strong>every report in every organization</strong>, on top of the built-in list. It comes from config
            files mounted on the API server — edit those and restart the API to change it; it can't be edited here.
          </p>
        </div>
        {total > 0 && (
          <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <ChevronRight size={14} className={`terms-set-chevron${open ? " open" : ""}`} aria-hidden="true" />
            {open ? "Hide terms" : "Show terms"}
          </button>
        )}
      </div>

      <p className="terms-floor-summary">
        <span>
          <strong>{floor.terms.length}</strong> protected
        </span>
        <span>
          <strong>{floor.exclude_terms.length}</strong> excluded
        </span>
        <span className="muted">Last checked {new Date(floor.synced_at).toLocaleString()}</span>
      </p>

      {total === 0 && (
        <p className="terms-empty">No config files are mounted, so only the built-in list applies.</p>
      )}

      {open && (
        <div className="terms-floor-body">
          {floor.terms.length > 0 && (
            <>
              <div className="terms-chip-label">Protected</div>
              <TermChips terms={floor.terms} />
            </>
          )}
          {floor.exclude_terms.length > 0 && (
            <>
              <div className="terms-chip-label">Never protected</div>
              <TermChips terms={floor.exclude_terms} muted />
            </>
          )}
        </div>
      )}

      {sources.length > 0 && (
        <dl className="terms-floor-sources">
          {sources.map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd className="mono">{floor.source_paths[key]}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
